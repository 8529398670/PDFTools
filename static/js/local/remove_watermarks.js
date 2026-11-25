// Remove watermarks, in the browser: app/actions/remove_watermarks.py and
// its detectors and removers (app/actions/watermarks/), on the PDF side in
// wm_core.js. Each detector here is its Python namesake, line for line where
// it can be, so a finding has the same id, words and confidence on both
// engines, and "Remove selected" can follow a check made on the other.
//
// The PDF is read with two qpdf --json calls (structure, then the decoded
// data of only the streams that are read), changed in memory, and the
// changed objects are written back with --update-from-json.
const LocalWatermarks = ( () => {
  const core = typeof WmPdf !== "undefined"
    ? { WmPy , WmPdf , WmContent , WmText , WmMatrix , WmDocument }
    : require( "./wm_core.js" );
  const { WmPy: Py , WmPdf: Pdf , WmContent: Content , WmText: Text , WmMatrix: Matrix , WmDocument: Doc } = core;

  // ---- vocab.py ------------------------------------------------------------------

  const BUILTIN_PHRASES = [
    "CONFIDENTIAL", "DO NOT COPY", "DO NOT DISTRIBUTE", "NOT FOR DISTRIBUTION", "DRAFT", "SAMPLE", "SPECIMEN", "VOID",
    "EXPIRED", "SUPERSEDED", "Journal Pre-proof", "Uncorrected proof", "Accepted Manuscript", "For review only",
    "For peer review", "Downloaded from", "Licensed to", "Evaluation copy", "Evaluation only", "Trial version",
    "Demo version", "Unregistered version", "Unlicensed copy", "Created with", "This watermark", "Internal use only",
    "Preview copy",
  ];
  const LINE_STARTERS = new Set( [ "Downloaded from" , "Licensed to" , "Created with" , "This watermark" ] );
  const NAME_HINTS = /stamp|watermark|wmark|overlay|background|bg[-_]?mark|confidential|draft|banner|ribbon|header[-_]?mark|footer[-_]?mark/i;
  const BENIGN_HINTS = /logo|brand|crest|seal|signature|icon/i;

  const needsBoundary = ( phrase ) => phrase.split( /\s+/ ).filter( Boolean ).length === 1;

  function looksLikeWatermarkText( text ) {
    const hay = Text.squash( Array.from( text ) ).chars;
    const hits = [];
    for ( const phrase of BUILTIN_PHRASES ) {
      const key = Text.squash( Array.from( phrase ) ).chars;
      if ( !key.length ) continue;
      for ( let at = find( hay , key , 0 ) ; at >= 0 ; at = find( hay , key , at + 1 ) ) {
        if ( !needsBoundary( phrase ) || standalone( hay , at , at + key.length ) ) {
          hits.push( phrase );
          break;
        }
      }
    }
    return hits;
  }

  function find( hay , key , from ) {
    outer: for ( let at = from ; at + key.length <= hay.length ; at++ ) {
      for ( let j = 0 ; j < key.length ; j++ ) if ( hay[ at + j ] !== key[ j ] ) continue outer;
      return at;
    }
    return -1;
  }

  function standalone( hay , start , end ) {
    const before = start > 0 ? hay[ start - 1 ] : "";
    const after = end < hay.length ? hay[ end ] : "";
    return !( ( before && Py.isalpha( before ) ) || ( after && Py.isalpha( after ) ) );
  }

  // ---- model.py --------------------------------------------------------------------

  class Candidate {
    constructor( detector , kind , description , pages , payload ) {
      this.detector = detector;
      this.kind = kind;
      this.description = description;
      this.pages = pages || [];
      this.evidence = [];
      this.payload = payload || {};
      this.forced = null;
    }

    get confidence() {
      if ( this.forced !== null ) return clamp( this.forced );
      let total = 0;
      for ( const item of this.evidence ) total += item.weight;
      return clamp( 0.5 + total );
    }

    get actionable() { return this.kind !== "image_page"; }

    add( label , weight ) { this.evidence.push( { label , weight: weight || 0 } ); }

    pageSummary() {
      const nums = [ ...new Set( this.pages.map( ( p ) => p + 1 ) ) ].sort( ( a , b ) => a - b );
      if ( !nums.length ) return "-";
      const runs = [];
      for ( const n of nums ) {
        if ( runs.length && n === runs[ runs.length - 1 ][ 1 ] + 1 ) runs[ runs.length - 1 ][ 1 ] = n;
        else runs.push( [ n , n ] );
      }
      return runs.map( ( [ a , b ] ) => a === b ? String( a ) : a + "-" + b ).join( ", " );
    }

    toDict() {
      return {
        detector: this.detector,
        kind: this.kind,
        description: this.description,
        pages: [ ...new Set( this.pages ) ].sort( ( a , b ) => a - b ).map( ( p ) => p + 1 ),
        page_summary: this.pageSummary(),
        confidence: Py.round3( this.confidence ),
        actionable: this.actionable,
        evidence: this.evidence.map( ( item ) => ( { label: item.label , weight: item.weight } ) ),
      };
    }
  }

  const clamp = ( v ) => Math.max( 0 , Math.min( 1 , v ) );

  // ---- detectors --------------------------------------------------------------------

  // detect/annots.py
  const ANNOT_SUBTYPES = { "/Watermark": 0.95 , "/Stamp": 0.75 , "/FreeText": 0.4 };

  function detectAnnots( doc ) {
    const pdf = doc.pdf;
    const out = [];
    pdf.pageRefs.forEach( ( pageRef , pindex ) => {
      const annots = pdf.get( pageRef , "/Annots" );
      if ( !Array.isArray( annots ) ) return;
      annots.forEach( ( raw , aindex ) => {
        const annot = pdf.resolve( raw );
        if ( !annot || typeof annot !== "object" || Array.isArray( annot ) ) return;
        const subtype = Pdf.text( pdf.get( annot , "/Subtype" ) || "" );
        if ( !( subtype in ANNOT_SUBTYPES ) ) return;
        let contents = "";
        for ( const key of [ "/Contents" , "/T" , "/NM" ] ) {
          const value = pdf.get( annot , key );
          if ( value !== null ) contents += " " + Pdf.text( value );
        }
        const shown = Py.strip( contents );
        const cand = new Candidate( "annot" , "annot" ,
          subtype.replace( /^\/+/ , "" ) + " annotation on page " + ( pindex + 1 ) + ( shown ? ": " + Py.repr( Array.from( shown ).slice( 0 , 60 ).join( "" ) ) : "" ) ,
          [ pindex ] , { page: pindex , index: aindex , subtype } );
        cand.add( "annotation subtype is " + subtype , 0 );
        let bump = 0;
        const hits = looksLikeWatermarkText( contents );
        if ( hits.length ) {
          cand.add( "text says " + hits.slice( 0 , 3 ).join( ", " ) , 0 );
          bump += 0.2;
        }
        if ( NAME_HINTS.test( contents ) ) bump += 0.15;
        const flagsValue = pdf.get( annot , "/F" );
        const flags = typeof flagsValue === "number" ? Math.trunc( flagsValue ) : 0;
        if ( flags & 2 ) { cand.add( "flagged hidden" , 0 ); bump -= 0.2; }
        if ( flags & 4 ) { cand.add( "flagged print-always (stamped onto output)" , 0 ); bump += 0.1; }
        cand.forced = Math.max( 0 , Math.min( 1 , ANNOT_SUBTYPES[ subtype ] + bump ) );
        out.push( cand );
      } );
    } );
    return out;
  }

  // detect/imagepage.py
  function detectImagePages( doc ) {
    const flattened = [];
    for ( let pindex = 0 ; pindex < doc.pageCount ; pindex++ ) {
      const images = doc.invocations.filter( ( inv ) => inv.page === pindex && inv.subtype === "Image" );
      if ( !images.length ) continue;
      let textChars = 0;
      for ( const scope of doc.scopes.values() ) {
        if ( scope.pages.has( pindex ) ) textChars += Array.from( scope.text ).filter( ( ch ) => !Py.isspace( ch ) ).length;
      }
      if ( textChars > 50 ) continue;
      const [ x0 , y0 , x1 , y1 ] = doc.pageBox( pindex );
      const area = Math.max( ( x1 - x0 ) * ( y1 - y0 ) , 1 );
      for ( const inv of images ) {
        const sx = Math.hypot( inv.ctm[ 0 ] , inv.ctm[ 1 ] );
        const sy = Math.hypot( inv.ctm[ 2 ] , inv.ctm[ 3 ] );
        if ( ( sx * sy ) / area >= 0.8 ) {
          flattened.push( pindex );
          break;
        }
      }
    }
    if ( !flattened.length ) return [];
    const cand = new Candidate( "imagepage" , "image_page" ,
      flattened.length + " page(s) are a single full-page image with no text layer -- any watermark is part of the pixels" ,
      flattened , { pages: flattened } );
    cand.add( "page content is one full-page image" , 0 );
    cand.add( "nothing to remove structurally; reported for information only" , 0 );
    cand.forced = 0;
    return [ cand ];
  }

  // detect/ocg.py
  function detectOcg( doc ) {
    const pdf = doc.pdf;
    const root = pdf.resolve( pdf.objects.trailer.value[ "/Root" ] );
    const ocprops = pdf.get( root , "/OCProperties" );
    if ( ocprops === null ) return [];
    const groups = pdf.get( ocprops , "/OCGs" );
    if ( !Array.isArray( groups ) ) return [];
    const out = [];
    for ( const raw of groups ) {
      const ocg = pdf.resolve( raw );
      if ( !ocg || typeof ocg !== "object" ) continue;
      const name = Pdf.text( pdf.get( ocg , "/Name" ) || "" );
      if ( !NAME_HINTS.test( name ) ) continue;
      const target = doc.objkey( ocg , raw );
      const cand = new Candidate( "ocg" , "ocg" , "optional-content layer named " + Py.repr( Py.strip( name , "()" ) ) ,
        Array.from( { length: doc.pageCount } , ( _ , i ) => i ) , { target , name } );
      cand.add( "layer name matches watermark vocabulary: " + Py.repr( Py.strip( name , "()" ) ) , 0.3 );
      const def = pdf.get( ocprops , "/D" );
      const off = def !== null ? pdf.get( def , "/OFF" ) : null;
      if ( Array.isArray( off ) && off.some( ( one ) => doc.objkey( pdf.resolve( one ) , one ) === target ) ) {
        cand.add( "layer is off by default (already not shown)" , -0.2 );
      }
      out.push( cand );
    }
    return out;
  }

  // detect/phrases.py
  const USER_CONFIDENCE = 0.95;
  const BUILTIN_CONFIDENCE = 0.6;
  const BUILTIN_MAX_BLOCK = 120;

  function excerpt( chars , start , end ) {
    const lo = Math.max( 0 , start - 24 );
    const hi = Math.min( chars.length , end + 24 );
    const snippet = chars.slice( lo , hi ).join( "" ).replace( /\n/g , " " );
    return ( lo > 0 ? "..." : "" ) + snippet + ( hi < chars.length ? "..." : "" );
  }

  function detectPhrases( doc , opts ) {
    const jobs = [];
    for ( const phrase of opts.phrases ) if ( Py.strip( phrase ) ) jobs.push( [ "phrase" , phrase , USER_CONFIDENCE , false ] );
    for ( const rx of opts.regexes ) if ( Py.strip( rx ) ) jobs.push( [ "regex" , rx , USER_CONFIDENCE , false ] );
    if ( !opts.noBuiltin ) for ( const phrase of BUILTIN_PHRASES ) jobs.push( [ "builtin" , phrase , BUILTIN_CONFIDENCE , needsBoundary( phrase ) ] );
    const out = [];
    for ( const [ source , needle , conf , boundary ] of jobs ) {
      const hits = [];
      const pages = new Set();
      const samples = [];
      let proseHits = 0;
      let whole = false;
      for ( const scope of doc.scopes.values() ) {
        if ( !scope.blocks.length ) continue;
        let found = false;
        scope.blocks.forEach( ( block , bi ) => {
          let spans = source === "regex" ? block.searchRegex( needle ) : block.search( needle , boundary );
          if ( !spans.length ) return;
          const longBlock = Array.from( Py.strip( block.text ) ).length > BUILTIN_MAX_BLOCK;
          if ( source === "builtin" && longBlock ) return;
          if ( longBlock ) proseHits += spans.length;
          if ( source === "builtin" && LINE_STARTERS.has( needle ) ) {
            whole = true;
            spans = [ [ 0 , block.chars.length ] ];
          }
          for ( const [ s , e ] of spans ) {
            hits.push( [ scope.key , bi , ...block.slotSpan( s , e ) ] );
            if ( samples.length < 2 ) samples.push( excerpt( block.chars , s , e ) );
          }
          found = true;
        } );
        if ( found ) scope.pages.forEach( ( p ) => pages.add( p ) );
      }
      if ( !hits.length ) continue;
      const label = source === "regex" ? "pattern" : "phrase";
      const cand = new Candidate( "phrase" , "text" ,
        hits.length + " match(es) for " + label + " " + Py.repr( needle ) + ( source === "builtin" ? " (from the builtin list)" : "" ) ,
        [ ...pages ].sort( ( a , b ) => a - b ) , { hits , needle , source } );
      cand.forced = conf;
      cand.add( "found in: " + Py.repr( samples[ 0 ] ) );
      if ( samples.length > 1 ) cand.add( "also: " + Py.repr( samples[ 1 ] ) );
      if ( source === "builtin" ) {
        cand.add( "matched the builtin vocabulary, not a phrase you supplied" );
        cand.add( "only standalone text blocks were considered" );
      }
      if ( whole ) cand.add( "removes the whole line it begins, not just these words" );
      if ( proseHits ) cand.add( proseHits + " match(es) sit inside running text -- check these are really watermarks before removing" );
      out.push( cand );
    }
    return out;
  }

  // detect/textstyle.py
  const LIGHT_GREY = 0.55;
  const BIG_FONT = 24;
  const COLOUR_OPS = new Set( [ "g" , "rg" , "k" , "sc" , "scn" ] );

  function grayOf( operands , op ) {
    const vals = operands.filter( ( item ) => item.k === "n" ).map( ( item ) => item.v );
    if ( op === "g" && vals.length >= 1 ) return vals[ 0 ];
    if ( op === "rg" && vals.length >= 3 ) return ( vals[ 0 ] + vals[ 1 ] + vals[ 2 ] ) / 3;
    if ( op === "k" && vals.length >= 4 ) {
      const [ c , m , y , kk ] = vals;
      return Math.max( 0 , 1 - Math.min( 1 , Math.max( c , m , y ) + kk ) );
    }
    if ( ( op === "sc" || op === "scn" ) && vals.length ) {
      let total = 0;
      for ( const v of vals ) total += v;
      return total / vals.length;
    }
    return null;
  }

  function styles( doc , scope ) {
    const pdf = doc.pdf;
    const gstates = pdf.get( scope.resources , "/ExtGState" );
    const out = new Map();
    let alpha = 1;
    let grey = null;
    let ctm = [ 1 , 0 , 0 , 1 , 0 , 0 ];
    let render = 0;
    const stack = [];
    let cur = null;
    let start = -1;
    const six = ( operands ) => operands.slice( 0 , 6 ).every( ( item ) => item.k === "n" ) ? operands.slice( 0 , 6 ).map( ( item ) => item.v ) : null;
    const note = ( st ) => {
      const full = Matrix.mul( st.tm , st.ctm );
      if ( Matrix.rotated( full ) ) st.rotated = true;
      const scale = Math.max( Math.sqrt( full[ 0 ] ** 2 + full[ 1 ] ** 2 ) , Math.sqrt( full[ 2 ] ** 2 + full[ 3 ] ** 2 ) );
      st.maxSize = Math.max( st.maxSize , st.fontSize * scale );
    };
    const alphaOf = ( operands ) => {
      if ( !operands.length || gstates === null ) return null;
      const gs = pdf.get( gstates , Doc.nameOf( operands[ 0 ] ) );
      const ca = gs !== null ? pdf.get( gs , "/ca" ) : null;
      return typeof ca === "number" ? ca : null;
    };
    scope.instructions.forEach( ( instr , idx ) => {
      const op = instr.op;
      const operands = instr.operands;
      if ( op === "q" ) stack.push( [ alpha , grey , ctm ] );
      else if ( op === "Q" ) { if ( stack.length ) [ alpha , grey , ctm ] = stack.pop(); }
      else if ( op === "cm" && operands.length >= 6 && cur === null ) {
        const m = six( operands );
        if ( m ) ctm = Matrix.mul( m , ctm );
      } else if ( op === "gs" ) {
        const value = alphaOf( operands );
        if ( value !== null ) {
          alpha = value;
          if ( cur ) cur.minAlpha = Math.min( cur.minAlpha , value );
        }
      } else if ( COLOUR_OPS.has( op ) ) {
        const val = grayOf( operands , op );
        if ( val !== null ) {
          grey = val;
          if ( cur ) cur.grey = val;
        }
      } else if ( op === "BT" ) {
        cur = { rotated: false , maxSize: 0 , minAlpha: alpha , grey , fontSize: 0 , invisible: false , ctm , tm: [ 1 , 0 , 0 , 1 , 0 , 0 ] };
        start = idx;
      } else if ( op === "ET" ) {
        if ( cur && start >= 0 ) {
          cur.invisible = render === 3;
          out.set( start , cur );
        }
        cur = null;
        start = -1;
      } else if ( op === "Tr" && operands.length ) {
        if ( operands[ 0 ].k === "n" ) render = Math.trunc( operands[ 0 ].v );
      } else if ( cur ) {
        if ( op === "Tf" && operands.length >= 2 ) {
          if ( operands[ 1 ].k === "n" ) cur.fontSize = Math.abs( operands[ 1 ].v );
          note( cur );
        } else if ( op === "Tm" && operands.length >= 6 ) {
          const m = six( operands );
          if ( m ) {
            cur.tm = m;
            note( cur );
          }
        }
      }
    } );
    return out;
  }

  function detectTextStyle( doc ) {
    const groups = new Map();
    for ( const scope of doc.scopes.values() ) {
      if ( !scope.blocks.length ) continue;
      const found = styles( doc , scope );
      scope.blocks.forEach( ( block , bi ) => {
        const body = Py.strip( block.text );
        if ( !body || Array.from( body ).length > 120 ) return;
        const st = found.get( block.startInstr );
        if ( !st || st.invisible ) return;
        if ( !groups.has( body ) ) groups.set( body , [] );
        groups.get( body ).push( [ scope , bi , st ] );
      } );
    }
    const out = [];
    const totalPages = Math.max( doc.pageCount , 1 );
    for ( const [ body , members ] of groups ) {
      const pages = [ ...new Set( members.flatMap( ( [ scope ] ) => [ ...scope.pages ] ) ) ].sort( ( a , b ) => a - b );
      const rotated = members.some( ( [ , , st ] ) => st.rotated );
      const minAlpha = Math.min( ...members.map( ( [ , , st ] ) => st.minAlpha ) );
      const maxSize = Math.max( ...members.map( ( [ , , st ] ) => st.maxSize ) );
      const greys = members.map( ( [ , , st ] ) => st.grey ).filter( ( g ) => g !== null && g >= LIGHT_GREY && g < 1 );
      const short = Array.from( body ).slice( 0 , 48 ).join( "" );
      const cand = new Candidate( "textstyle" , "text" , "styled text " + Py.repr( short ) , pages , {
        hits: members.map( ( [ scope , bi ] ) => [ scope.key , bi , 0 , scope.blocks[ bi ].slots.length ] ),
        needle: short,
        source: "style",
      } );
      let style = 0;
      let strong = false;
      if ( rotated ) { cand.add( "drawn at an angle" , 0.2 ); style++; strong = true; }
      if ( minAlpha < 0.9 ) { cand.add( "semi-transparent (alpha " + Py.g( minAlpha ) + ")" , 0.2 ); style++; strong = true; }
      if ( maxSize >= BIG_FONT ) { cand.add( "oversized text (" + Py.g( maxSize ) + "pt)" , 0.15 ); style++; strong = true; }
      if ( greys.length ) { cand.add( "painted in light grey (" + Math.max( ...greys ).toFixed( 2 ) + ")" , 0.15 ); style++; }
      const repeated = pages.length > 1;
      if ( repeated ) cand.add( "repeated across " + pages.length + "/" + totalPages + " pages" , 0.15 );
      if ( style >= 2 || ( strong && repeated ) ) out.push( cand );
    }
    return out;
  }

  // detect/xobjects.py
  const PAINT_OPS = new Set( [ "m" , "l" , "c" , "v" , "y" , "re" , "f" , "f*" , "F" , "B" , "B*" , "b" , "b*" , "S" , "s" ] );
  const FULL_PAGE_AREA = 0.55;
  const REPEAT_THRESHOLD = 0.6;

  function metadataStrings( pdf , obj ) {
    const out = [];
    for ( const key of [ "/PTEX.FileName" , "/Name" , "/Title" , "/OCGName" ] ) {
      const value = pdf.get( obj , key );
      if ( value !== null ) out.push( Pdf.text( value ) );
    }
    return out;
  }

  function areaFraction( pdf , inv , w , h ) {
    if ( w <= 0 || h <= 0 ) return 0;
    if ( inv.subtype === "Image" ) {
      const [ a , b , c , d ] = inv.ctm;
      return Math.min( 1 , Math.abs( a * d - b * c ) / ( w * h ) );
    }
    const box = pdf.get( inv.obj , "/BBox" );
    if ( !Array.isArray( box ) || box.length < 4 ) return 0;
    const [ x0 , y0 , x1 , y1 ] = box.slice( 0 , 4 ).map( ( one ) => pdf.resolve( one ) );
    if ( ![ x0 , y0 , x1 , y1 ].every( ( one ) => typeof one === "number" ) ) return 0;
    const sx = Math.sqrt( inv.ctm[ 0 ] ** 2 + inv.ctm[ 1 ] ** 2 );
    const sy = Math.sqrt( inv.ctm[ 2 ] ** 2 + inv.ctm[ 3 ] ** 2 );
    return Math.min( 1 , ( Math.abs( x1 - x0 ) * sx * Math.abs( y1 - y0 ) * sy ) / ( w * h ) );
  }

  function shorten( s , limit ) {
    limit = limit || 60;
    const chars = Array.from( Py.strip( s , "()/ " ) );
    return chars.length <= limit ? chars.join( "" ) : "..." + chars.slice( chars.length - ( limit - 3 ) ).join( "" );
  }

  function detectXObjects( doc ) {
    const pdf = doc.pdf;
    const byTarget = new Map();
    for ( const inv of doc.invocations ) {
      if ( !byTarget.has( inv.target ) ) byTarget.set( inv.target , [] );
      byTarget.get( inv.target ).push( inv );
    }
    const firstOrder = new Map();
    for ( const inv of doc.invocations ) {
      if ( inv.depth === 0 && ( !firstOrder.has( inv.page ) || inv.order < firstOrder.get( inv.page ) ) ) firstOrder.set( inv.page , inv.order );
    }
    const totalPages = Math.max( doc.pageCount , 1 );
    const out = [];
    for ( const [ target , invs ] of byTarget ) {
      const pages = [ ...new Set( invs.map( ( inv ) => inv.page ) ) ].sort( ( a , b ) => a - b );
      if ( invs[ 0 ].subtype !== "Form" && invs[ 0 ].subtype !== "Image" ) continue;
      const obj = invs[ 0 ].obj;
      const frac = pages.length / totalPages;
      const [ px0 , py0 , px1 , py1 ] = doc.pageBox( pages[ 0 ] );
      const area = areaFraction( pdf , invs[ 0 ] , px1 - px0 , py1 - py0 );
      const names = [ invs[ 0 ].name ].concat( metadataStrings( pdf , obj ) );
      const scope = doc.scopes.get( target ) || null;
      const innerText = scope ? scope.text : "";
      const decodable = Array.from( innerText ).filter( ( ch ) => !Py.isspace( ch ) && ch !== "\ufffd" ).length;
      const shown = target.startsWith( "direct" ) ? target : target.split( " " )[ 0 ];
      const cand = new Candidate( "xobject" , "xobject" ,
        invs[ 0 ].subtype + " XObject /" + invs[ 0 ].name + " (object " + shown + ") painted on " + pages.length + "/" + totalPages + " pages" ,
        pages , { target , invocations: invs , name: invs[ 0 ].name , subtype: invs[ 0 ].subtype } );

      if ( frac >= 0.99 && totalPages > 1 ) cand.add( "painted on every page (" + pages.length + "/" + totalPages + ")" , 0.22 );
      else if ( frac >= REPEAT_THRESHOLD && totalPages > 1 ) cand.add( "painted on most pages (" + pages.length + "/" + totalPages + ")" , 0.18 );
      if ( pages.length > 1 && ctmsAgree( invs ) ) cand.add( "painted at an identical position on every page" , 0.12 );
      if ( area >= FULL_PAGE_AREA ) cand.add( "covers " + Py.percent( area , 0 ) + " of the page (full-page overlay)" , 0.18 );
      const hinted = names.filter( ( s ) => NAME_HINTS.test( s ) );
      if ( hinted.length ) cand.add( "name/metadata says " + Py.repr( shorten( hinted[ 0 ] ) ) , 0.28 );
      const overlay = invs.every( ( inv ) => inv.order > ( firstOrder.has( inv.page ) ? firstOrder.get( inv.page ) : -1 ) ) && invs.length > 0;
      const repeated = pages.length > 1;
      if ( overlay && area >= 0.2 ) cand.add( "drawn on top of the page's main content" , 0.12 );
      else if ( !overlay && invs[ 0 ].subtype === "Image" && area >= 0.8 ) cand.add( "a full-page picture under everything: the scan itself or the page's paper" , -0.55 );
      else if ( !overlay && !repeated ) cand.add( "painted first and only once: this is the page's own content" , -0.4 );
      const minAlpha = Math.min( 1 , ...invs.map( ( inv ) => inv.alpha ) );
      if ( minAlpha < 1 ) cand.add( "painted with transparency (alpha " + Py.g( minAlpha ) + ")" , 0.15 );
      if ( invs.some( ( inv ) => Matrix.rotated( inv.ctm ) ) ) cand.add( "painted at an angle" , 0.12 );
      const phraseHits = decodable < 200 ? looksLikeWatermarkText( innerText ) : [];
      if ( phraseHits.length ) cand.add( "contains watermark wording: " + phraseHits.slice( 0 , 3 ).join( ", " ) , 0.2 );
      if ( scope && pages.length > 1 && area >= FULL_PAGE_AREA ) {
        const paint = scope.instructions.filter( ( ins ) => PAINT_OPS.has( ins.op ) ).length;
        if ( paint >= 50 && decodable < 10 ) cand.add( paint + " path-painting operators but no readable text (lettering drawn as vector outlines)" , 0.2 );
      }
      if ( pages.length === 1 && totalPages > 1 ) cand.add( "appears on only one page" , -0.35 );
      if ( decodable > 200 ) cand.add( "holds " + decodable + " characters of readable text (looks like page content)" , -0.35 );
      if ( area > 0 && area < 0.05 ) cand.add( "covers only " + Py.percent( area , 1 ) + " of the page (spot element)" , -0.35 );
      const benign = names.filter( ( s ) => BENIGN_HINTS.test( s ) );
      if ( benign.length && !hinted.length ) cand.add( "name suggests branding, not a watermark: " + Py.repr( shorten( benign[ 0 ] ) ) , -0.15 );
      out.push( cand );
    }
    return out;
  }

  function ctmsAgree( invs ) {
    if ( invs.length < 2 ) return true;
    const first = invs[ 0 ].ctm;
    return invs.slice( 1 ).every( ( inv ) => inv.ctm.every( ( value , i ) => Math.abs( value - first[ i ] ) <= 2 ) );
  }

  // Registered in the order Python imports them, which ties are left in.
  const DETECTORS = [
    [ "annot" , detectAnnots ], [ "imagepage" , detectImagePages ], [ "ocg" , detectOcg ],
    [ "phrase" , detectPhrases ], [ "textstyle" , detectTextStyle ], [ "xobject" , detectXObjects ],
  ];

  function runAll( doc , opts , only ) {
    const found = [];
    for ( const [ name , detect ] of DETECTORS ) {
      if ( only && only.size && !only.has( name ) ) continue;
      try { found.push( ...detect( doc , opts ) ); } catch ( error ) { /* one detector failing must not sink the scan */ }
    }
    return found.map( ( cand , i ) => [ cand , i ] ).sort( ( [ a , i ] , [ b , j ] ) => {
      if ( a.confidence !== b.confidence ) return b.confidence - a.confidence;
      if ( a.detector !== b.detector ) return a.detector < b.detector ? -1 : 1;
      if ( a.description !== b.description ) return a.description < b.description ? -1 : 1;
      return i - j;
    } ).map( ( [ cand ] ) => cand );
  }

  // ---- removers (remove/) -------------------------------------------------------------

  function neutralize( instr ) {
    if ( instr.op === "'" ) return [ Content.make( "T*" ) ];
    if ( instr.op === '"' && instr.operands.length >= 2 ) {
      return [ Content.make( "Tw" , [ instr.operands[ 0 ] ] ) , Content.make( "Tc" , [ instr.operands[ 1 ] ] ) , Content.make( "T*" ) ];
    }
    return [];
  }

  function newEdits() {
    return { drop: new Map() , replace: new Map() , operands: new Map() , resources: new Map() , annots: new Map() , ocgs: new Set() };
  }

  const bucket = ( map , key , make ) => {
    if ( !map.has( key ) ) map.set( key , make() );
    return map.get( key );
  };

  function planText( doc , cand , edits ) {
    const hits = cand.payload.hits || [];
    if ( !hits.length ) return [ false , "no recorded text matches" ];
    const perBlock = new Map();
    for ( const [ scopeKey , bi , start , end ] of hits ) {
      const scope = doc.scopes.get( scopeKey );
      if ( !scope || bi >= scope.blocks.length ) continue;
      const set = bucket( perBlock , scopeKey + "\u0000" + bi , () => ( { scopeKey , bi , slots: new Set() } ) ).slots;
      for ( let i = start ; i < Math.min( end , scope.blocks[ bi ].slots.length ) ; i++ ) set.add( i );
    }
    let planned = 0;
    for ( const { scopeKey , bi , slots } of perBlock.values() ) {
      if ( !slots.size ) continue;
      const scope = doc.scopes.get( scopeKey );
      const block = scope.blocks[ bi ];
      if ( slots.size >= block.slots.length ) {
        for ( const idx of new Set( block.slots.map( ( slot ) => slot.instr ) ) ) {
          const instr = scope.instructions[ idx ];
          if ( Text.SHOW_OPS.has( instr.op ) ) bucket( edits.replace , scopeKey , () => new Map() ).set( idx , neutralize( instr ) );
        }
        planned++;
        continue;
      }
      for ( const si of [ ...slots ].sort( ( a , b ) => a - b ) ) {
        const slot = block.slots[ si ];
        const perScope = bucket( edits.operands , scopeKey , () => new Map() );
        bucket( perScope , slot.instr + ":" + slot.operand + ":" + slot.array , () => [] ).push( [ slot.start , slot.length , slot.advance ] );
        planned++;
      }
    }
    return planned ? [ true , "" ] : [ false , "matches no longer resolve to any glyphs" ];
  }

  function planXObject( doc , cand , edits ) {
    let touched = 0;
    for ( const inv of cand.payload.invocations || [] ) {
      const scope = doc.scopes.get( inv.scope );
      if ( !scope || inv.instr < 0 ) continue;
      const instr = scope.instructions[ inv.instr ];
      if ( !instr || instr.op !== "Do" || !instr.operands.length ) continue;
      if ( Doc.nameOf( instr.operands[ 0 ] ).replace( /^\/+/ , "" ) !== inv.name.replace( /^\/+/ , "" ) ) continue;
      bucket( edits.drop , inv.scope , () => new Set() ).add( inv.instr );
      bucket( edits.resources , inv.scope , () => new Set() ).add( inv.name );
      touched++;
    }
    return touched ? [ true , "" ] : [ false , "could not match any Do operator to remove" ];
  }

  function planAnnot( doc , cand , edits ) {
    bucket( edits.annots , cand.payload.page , () => new Set() ).add( cand.payload.index );
    return [ true , "" ];
  }

  function refersTo( doc , operand , props , target ) {
    if ( operand.k !== "name" ) return false;
    const raw = props !== null ? doc.pdf.raw( props , operand.v ) : null;
    const resolved = doc.pdf.resolve( raw );
    if ( resolved === null ) return false;
    if ( doc.objkey( resolved , raw ) === target ) return true;
    const innerRaw = doc.pdf.raw( resolved , "/OCGs" );
    const inner = doc.pdf.resolve( innerRaw );
    if ( inner === null ) return false;
    if ( doc.objkey( inner , innerRaw ) === target ) return true;
    return Array.isArray( inner ) && inner.some( ( one ) => doc.objkey( doc.pdf.resolve( one ) , one ) === target );
  }

  function planOcg( doc , cand , edits ) {
    const target = cand.payload.target;
    edits.ocgs.add( target );
    for ( const [ key , scope ] of doc.scopes ) {
      const props = doc.pdf.get( scope.resources , "/Properties" );
      let depth = 0;
      let start = -1;
      scope.instructions.forEach( ( instr , idx ) => {
        if ( instr.op === "BDC" || instr.op === "BMC" ) {
          if ( start >= 0 ) { depth++; return; }
          const ops = instr.operands;
          if ( instr.op === "BDC" && ops.length >= 2 && ops[ 0 ].k === "name" && ops[ 0 ].v === "/OC" && refersTo( doc , ops[ 1 ] , props , target ) ) {
            start = idx;
            depth = 0;
          }
        } else if ( instr.op === "EMC" && start >= 0 ) {
          if ( depth === 0 ) {
            const set = bucket( edits.drop , key , () => new Set() );
            for ( let i = start ; i <= idx ; i++ ) set.add( i );
            start = -1;
          } else depth--;
        }
      } );
    }
    return [ true , "" ];
  }

  const PLANNERS = { xobject: planXObject , text: planText , annot: planAnnot , ocg: planOcg };

  function plan( doc , chosen ) {
    const edits = newEdits();
    const report = { applied: [] , operators: 0 , glyphs: 0 , annotations: 0 , layers: 0 , resources: 0 };
    for ( const cand of chosen ) {
      if ( !cand.actionable || !PLANNERS[ cand.kind ] ) continue;
      let answer;
      try { answer = PLANNERS[ cand.kind ]( doc , cand , edits ); } catch ( error ) { continue; }
      if ( answer[ 0 ] ) report.applied.push( cand );
    }
    return { edits , report };
  }

  // remove._pieces
  function pieces( raw , ranges ) {
    const cuts = ranges.filter( ( [ s , l ] ) => s >= 0 && s + l <= raw.length ).sort( ( a , b ) => a[ 0 ] - b[ 0 ] || a[ 1 ] - b[ 1 ] );
    const out = [];
    let pos = 0;
    let removed = 0;
    let exact = true;
    let gap = 0;
    let inGap = false;
    for ( const [ start , length , advance ] of cuts ) {
      if ( start < pos ) continue;
      if ( start > pos ) {
        if ( inGap ) { out.push( gap ); gap = 0; inGap = false; }
        out.push( raw.subarray( pos , start ) );
      }
      if ( advance === null || advance === undefined ) exact = false;
      else gap -= advance;
      inGap = true;
      removed++;
      pos = start + length;
    }
    if ( inGap ) out.push( gap );
    if ( pos < raw.length ) out.push( raw.subarray( pos ) );
    return { out , removed , exact };
  }

  function asOperands( list ) {
    const out = [];
    for ( const piece of list ) {
      if ( piece instanceof Uint8Array ) { if ( piece.length ) out.push( { k: "str" , v: piece } ); }
      else if ( piece ) out.push( { k: "n" , v: Py.round3( piece ) } );
    }
    return out;
  }

  // remove._rewrite
  function rewrite( instr , slots ) {
    const operands = instr.operands.slice();
    let total = 0;
    const arrays = new Map();
    const plains = new Map();
    for ( const [ key , ranges ] of slots ) {
      const [ , opIdx , arrIdx ] = key.split( ":" ).map( Number );
      if ( arrIdx >= 0 ) bucket( arrays , opIdx , () => new Map() ).set( arrIdx , ranges );
      else plains.set( opIdx , ranges );
    }
    if ( instr.op === "TJ" ) {
      for ( const [ opIdx , elements ] of arrays ) {
        if ( opIdx >= operands.length || operands[ opIdx ].k !== "arr" ) continue;
        const rebuilt = [];
        operands[ opIdx ].v.forEach( ( item , arrIdx ) => {
          if ( !elements.has( arrIdx ) || item.k !== "str" ) { rebuilt.push( item ); return; }
          let cut = pieces( item.v , elements.get( arrIdx ) );
          total += cut.removed;
          const kept = cut.exact ? cut.out : cut.out.filter( ( p ) => p instanceof Uint8Array );
          rebuilt.push( ...asOperands( kept ) );
        } );
        operands[ opIdx ] = { k: "arr" , v: rebuilt };
      }
      return { instrs: [ Content.make( "TJ" , operands ) ] , total };
    }
    const opIdx = instr.op === '"' ? 2 : 0;
    const ranges = plains.get( opIdx );
    if ( !ranges || opIdx >= operands.length || operands[ opIdx ].k !== "str" ) return { instrs: null , total: 0 };
    const cut = pieces( operands[ opIdx ].v , ranges );
    if ( !cut.exact ) {
      const kept = cut.out.filter( ( p ) => p instanceof Uint8Array );
      const size = kept.reduce( ( sum , p ) => sum + p.length , 0 );
      const joined = new Uint8Array( size );
      let at = 0;
      for ( const p of kept ) { joined.set( p , at ); at += p.length; }
      operands[ opIdx ] = { k: "str" , v: joined };
      return { instrs: [ Content.make( instr.op , operands ) ] , total: cut.removed };
    }
    return { instrs: neutralize( instr ).concat( [ Content.make( "TJ" , [ { k: "arr" , v: asOperands( cut.out ) } ] ) ] ) , total: cut.removed };
  }

  function apply( doc , edits , report ) {
    const pdf = doc.pdf;
    for ( const [ key , scope ] of doc.scopes ) {
      const drops = edits.drop.get( key ) || new Set();
      const replaces = edits.replace.get( key ) || new Map();
      const ops = edits.operands.get( key ) || new Map();
      if ( !drops.size && !replaces.size && !ops.size ) continue;
      const perInstr = new Map();
      for ( const [ slotKey , ranges ] of ops ) bucket( perInstr , Number( slotKey.split( ":" )[ 0 ] ) , () => new Map() ).set( slotKey , ranges );
      const rebuilt = [];
      scope.instructions.forEach( ( instr , idx ) => {
        if ( drops.has( idx ) ) { report.operators++; return; }
        if ( replaces.has( idx ) ) {
          report.operators++;
          report.glyphs += scope.blocks.reduce( ( sum , block ) => sum + block.slots.filter( ( slot ) => slot.instr === idx ).length , 0 );
          rebuilt.push( ...replaces.get( idx ) );
          return;
        }
        if ( perInstr.has( idx ) ) {
          const done = rewrite( instr , perInstr.get( idx ) );
          report.glyphs += done.total;
          rebuilt.push( ...( done.instrs || [ instr ] ) );
        } else rebuilt.push( instr );
      } );
      scope.instructions = rebuilt;
      scope.invalidate();
      scope.dirty = true;
    }

    // A resource name goes only once nothing using its dictionary paints it.
    if ( [ ...edits.resources.values() ].some( ( set ) => set.size ) ) {
      const stillUsed = new Map();
      for ( const scope of doc.scopes.values() ) {
        if ( scope.resources === null ) continue;
        const used = bucket( stillUsed , scope.resourcesKey , () => new Set() );
        for ( const instr of scope.instructions ) {
          if ( instr.op === "Do" && instr.operands.length ) used.add( Doc.nameOf( instr.operands[ 0 ] ).replace( /^\/+/ , "" ) );
        }
      }
      for ( const [ key , names ] of edits.resources ) {
        const scope = doc.scopes.get( key );
        if ( !scope || scope.resources === null ) continue;
        const used = stillUsed.get( scope.resourcesKey ) || new Set();
        for ( const name of names ) {
          if ( used.has( name.replace( /^\/+/ , "" ) ) ) continue;
          const xobjects = pdf.get( scope.resources , "/XObject" );
          const entry = "/" + name.replace( /^\/+/ , "" );
          if ( xobjects && typeof xobjects === "object" && Object.prototype.hasOwnProperty.call( xobjects , entry ) ) {
            delete xobjects[ entry ];
            pdf.touch( xobjects );
            report.resources++;
          }
        }
      }
    }

    for ( const [ pindex , indices ] of edits.annots ) {
      const pageRef = pdf.pageRefs[ pindex ];
      const page = pdf.resolve( pageRef );
      const annots = pdf.get( page , "/Annots" );
      if ( !Array.isArray( annots ) ) continue;
      const kept = annots.filter( ( _ , i ) => !indices.has( i ) );
      report.annotations += annots.length - kept.length;
      if ( kept.length ) page[ "/Annots" ] = kept;
      else delete page[ "/Annots" ];
      pdf.touch( pageRef );
    }

    if ( edits.ocgs.size ) {
      const rootRef = pdf.objects.trailer.value[ "/Root" ];
      const ocprops = pdf.get( rootRef , "/OCProperties" );
      if ( ocprops !== null ) {
        const keyOf = ( one ) => doc.objkey( pdf.resolve( one ) , one );
        const groups = pdf.get( ocprops , "/OCGs" );
        if ( Array.isArray( groups ) ) {
          const kept = groups.filter( ( one ) => !edits.ocgs.has( keyOf( one ) ) );
          report.layers += groups.length - kept.length;
          ocprops[ "/OCGs" ] = kept;
          pdf.touch( ocprops );
          if ( Pdf.isRef( pdf.resolve( rootRef )[ "/OCProperties" ] ) ) pdf.touch( pdf.resolve( rootRef )[ "/OCProperties" ] );
        }
        const def = pdf.get( ocprops , "/D" );
        if ( def !== null && typeof def === "object" ) {
          const without = ( items ) => items.filter( ( one ) => Array.isArray( one ) || !edits.ocgs.has( keyOf( one ) ) )
            .map( ( one ) => Array.isArray( one ) ? without( one ) : one );
          for ( const key of [ "/ON" , "/OFF" , "/Order" ] ) {
            const list = pdf.get( def , key );
            if ( Array.isArray( list ) ) {
              def[ key ] = without( list );
              pdf.touch( def );
            }
          }
        }
      }
    }
    return report;
  }

  // ---- the action -------------------------------------------------------------------

  async function sha( text ) {
    const digest = await crypto.subtle.digest( "SHA-256" , new TextEncoder().encode( text ) );
    return Array.from( new Uint8Array( digest ) , ( b ) => b.toString( 16 ).padStart( 2 , "0" ) ).join( "" );
  }

  // remove_watermarks.finding_id
  async function findingId( cand ) {
    const payload = cand.payload;
    let key;
    if ( cand.detector === "xobject" ) {
      key = payload.target.startsWith( "direct" ) ? payload.name + " [" + cand.pages.join( ", " ) + "]" : payload.target;
    } else if ( cand.detector === "phrase" || cand.detector === "textstyle" ) key = payload.source + " " + payload.needle;
    else if ( cand.detector === "annot" ) key = payload.page + " " + payload.index;
    else if ( cand.detector === "ocg" ) {
      const [ n , g ] = String( payload.target ).split( " " );
      key = "(" + n + ", " + g + ") " + payload.name;
    } else key = cand.description;
    return ( await sha( cand.detector + "|" + key ) ).slice( 0 , 12 );
  }

  async function finding( cand , applied ) {
    const record = cand.toDict();
    record.id = await findingId( cand );
    record.description = Array.from( record.description ).slice( 0 , 200 ).join( "" );
    record.evidence = record.evidence.slice( 0 , 8 ).map( ( e ) => ( { label: Array.from( e.label ).slice( 0 , 200 ).join( "" ) , weight: e.weight } ) );
    if ( record.pages.length > 2000 ) record.pages = record.pages.slice( 0 , 2000 );
    if ( applied !== null ) record.applied = applied;
    return record;
  }

  const DEFAULTS = { mode: "remove" , phrases: [] , regexes: [] , builtin: true , min_confidence: 0.5 , detectors: [] , picked: [] };
  const MAX_FINDINGS = 100;

  // The PDF, read: every object's structure, then the decoded data of the
  // streams the detectors read.
  function load( qpdf , source ) {
    const dump = qpdf.json( [ "--json=2" , "--json-key=pages" , "--json-key=qpdf" , "--json-stream-data=none" , source ] );
    const pdf = new Pdf( dump );
    const wanted = new Set();
    pdf.pageContents.forEach( ( refs ) => refs.forEach( ( ref ) => wanted.add( ref ) ) );
    for ( const [ key , entry ] of Object.entries( pdf.objects ) ) {
      if ( !key.startsWith( "obj:" ) ) continue;
      const dict = entry.stream ? entry.stream.dict : entry.value;
      if ( !dict || typeof dict !== "object" || Array.isArray( dict ) ) continue;
      if ( entry.stream && dict[ "/Subtype" ] === "/Form" ) wanted.add( key.slice( 4 ) );
      if ( Pdf.isRef( dict[ "/ToUnicode" ] ) ) wanted.add( dict[ "/ToUnicode" ] );
    }
    const refs = [ ...wanted ].filter( ( ref ) => pdf.isStream( ref ) );
    // In batches, so no one call has too long an argument list.
    for ( let at = 0 ; at < refs.length ; at += 2000 ) {
      const args = [ "--json=2" , "--json-key=qpdf" , "--json-stream-data=inline" , "--decode-level=generalized" ];
      refs.slice( at , at + 2000 ).forEach( ( ref ) => args.push( "--json-object=" + ref.replace( / R$/ , "" ).replace( " " , "," ) ) );
      args.push( source );
      const data = qpdf.json( args ).qpdf[ 1 ];
      for ( const [ key , entry ] of Object.entries( data ) ) {
        if ( entry.stream && pdf.objects[ key ] && pdf.objects[ key ].stream ) {
          // The decoded data, and the dictionary as that data reads it: a
          // filter qpdf could not undo stays named there, and the data is
          // then not used. The stream's own dictionary is kept as it is, for
          // writing back a stream whose data does not change.
          pdf.objects[ key ].stream.data = entry.stream.data;
          pdf.objects[ key ].stream.decodedDict = entry.stream.dict || {};
        }
      }
    }
    return pdf;
  }

  async function run( qpdf , source , work , options , hooks , sourceName ) {
    const pages = typeof LocalPages !== "undefined" ? LocalPages : require( "./pages.js" ).LocalPages;
    options = Object.assign( {} , DEFAULTS , options );
    hooks.progress( 0 , "" );
    for ( const pattern of options.regexes || [] ) {
      try { new RegExp( pattern , "u" ); } catch ( error ) {
        try { new RegExp( pattern ); } catch ( again ) { throw new Error( "bad_regex" ); }
      }
    }
    const pdf = load( qpdf , source );
    const doc = new Doc( pdf );
    hooks.progress( 0.3 , "" );
    const opts = { phrases: options.phrases || [] , regexes: options.regexes || [] , noBuiltin: !options.builtin };
    const found = runAll( doc , opts , new Set( options.detectors || [] ) );
    hooks.progress( 0.5 , "" );
    if ( options.mode === "check" ) {
      const findings = [];
      for ( const cand of found.slice( 0 , MAX_FINDINGS ) ) findings.push( await finding( cand , null ) );
      return { mode: "check" , pages: doc.pageCount , min_confidence: options.min_confidence , findings , more: Math.max( 0 , found.length - MAX_FINDINGS ) };
    }
    const ids = new Map();
    for ( const cand of found ) ids.set( cand , await findingId( cand ) );
    const wanted = new Set( options.picked || [] );
    const chosen = wanted.size
      ? found.filter( ( cand ) => cand.actionable && wanted.has( ids.get( cand ) ) )
      : found.filter( ( cand ) => cand.actionable && cand.confidence >= options.min_confidence );
    const { edits , report } = plan( doc , chosen );
    apply( doc , edits , report );
    const changed = report.operators || report.glyphs || report.annotations || report.layers || report.resources;
    const target = work + "/" + ( hooks.prefix || "" ) + "no-watermarks.pdf";
    await qpdf.prepare( target );
    let applied = new Set( report.applied.map( ( cand ) => ids.get( cand ) ) );
    if ( changed ) {
      doc.writeBack();
      const update = "/tmp/qpdf-watermarks.json";
      qpdf.write( update , JSON.stringify( pdf.update() ) );
      try {
        qpdf.ok( [ source , "--update-from-json=" + update , "--decode-level=none" , "--object-streams=preserve" , target ] );
      } finally {
        qpdf.remove( update );
      }
    } else {
      // Nothing to take out: the file as it was, so a chain goes on.
      qpdf.remove( target );
      await pages.copy( qpdf , source , target );
      applied = new Set();
    }
    hooks.progress( 0.9 , "" );
    const findings = [];
    for ( const cand of found.slice( 0 , MAX_FINDINGS ) ) findings.push( await finding( cand , applied.has( ids.get( cand ) ) ) );
    const name = pages.stem( sourceName ) + " - no watermarks.pdf";
    await hooks.output( name , target , { pages: doc.pageCount , first_page: 1 , last_page: doc.pageCount , title: "" } );
    hooks.progress( 1 , name );
    return {
      mode: "remove",
      pages: doc.pageCount,
      min_confidence: options.min_confidence,
      removed: applied.size,
      operators: report.operators,
      glyphs: report.glyphs,
      annotations: report.annotations,
      layers: report.layers,
      findings,
      more: Math.max( 0 , found.length - MAX_FINDINGS ),
    };
  }

  return { run , DEFAULTS , load , runAll , findingId };
} )();

if ( typeof module !== "undefined" && module.exports ) module.exports = { LocalWatermarks };
