// Split by bookmarks, in the browser: the same split as the server's
// app/actions/split_bookmarks.py, run by qpdf compiled to WebAssembly
// (static/vendor/qpdf/, built by scripts/build_qpdf_wasm.sh). The planning and
// naming are a line-for-line port of the Python, so the two engines make the
// same files; scripts/check_local_split.js runs both on the same PDFs and
// compares them.
//
// Nothing here touches the page. It runs in the split worker
// (static/js/local/worker.js) and under node for that check, given a qpdf to
// call (LocalQpdf below) and paths in qpdf's file system.
//
// How the work is done, all through qpdf's command line:
// - the outline is read with qpdf --json (its "outlines" key), which already
//   resolves named targets and GoTo actions to a page number;
// - each section is copied out with --empty --pages, as the server does, which
//   reads only the pages it copies from the source;
// - the section's own bookmarks are added, and links that now point nowhere
//   removed, with --update-from-json: the new objects as qpdf JSON, written
//   back without decoding any stream.
const LocalSplit = {
  DEPTH_LIMIT: 32,
  ITEMS_LIMIT: 200000,
  TITLE_MAX: 150,
  FRONT_MATTER: "Front matter",
  DEFAULTS: { level: 1 , front_matter: true , inner_bookmarks: true , numbered: true },

  // ---- reading ---------------------------------------------------------------

  // The outline as a tree of marks, in document order: { title , depth ,
  // page (from 0, or null) , order , children }.
  marks( qpdf , source , pageCount ) {
    const outlines = qpdf.json( [ "--json=2" , "--json-key=outlines" , source ] ).outlines || [];
    let counter = 0;
    const walk = ( items , depth ) => {
      const marks = [];
      if ( depth > this.DEPTH_LIMIT ) return marks;
      for ( const item of items ) {
        if ( counter >= this.ITEMS_LIMIT ) break;
        counter += 1;
        const mark = { title: String( item.title || "" ).trim() , depth: depth , page: this.pageOf( item , pageCount ) , order: counter };
        mark.children = walk( item.kids || [] , depth + 1 );
        marks.push( mark );
      }
      return marks;
    };
    return walk( outlines , 1 );
  },

  pageOf( item , pageCount ) {
    if ( Number.isInteger( item.destpageposfrom1 ) ) return item.destpageposfrom1 - 1;
    // A page number, as in a remote target; taken at its word (as pdf.py does).
    const dest = item.dest;
    if ( Array.isArray( dest ) && Number.isInteger( dest[ 0 ] ) && dest[ 0 ] >= 0 && dest[ 0 ] < pageCount ) return dest[ 0 ];
    return null;
  },

  pageCount( qpdf , source ) {
    const answer = qpdf.run( [ "--show-npages" , source ] );
    if ( answer.code !== 0 && answer.code !== 3 ) throw this.unreadable( answer );
    return Number( answer.out.trim() );
  },

  // What a PDF that cannot be opened says, as a language.yaml code under
  // library.invalid_ (the same as the server's import check).
  unreadable( answer ) {
    const said = answer.err || "";
    const error = new Error( /password/i.test( said ) ? "password" : /not a PDF|can't find PDF header|unable to find/i.test( said ) ? "not_pdf" : "damaged" );
    error.detail = said;
    return error;
  },

  walkMarks( marks , visit ) {
    marks.forEach( ( mark ) => { visit( mark ); this.walkMarks( mark.children , visit ); } );
  },

  // The quick look the dialog needs: pages, and how many bookmarks sit at each
  // level (about how many sections a split there makes).
  inspect( qpdf , source ) {
    const pages = this.pageCount( qpdf , source );
    const marks = this.marks( qpdf , source , pages );
    const levels = [];
    this.walkMarks( marks , ( mark ) => { levels[ mark.depth - 1 ] = ( levels[ mark.depth - 1 ] || 0 ) + 1; } );
    for ( let index = 0 ; index < levels.length ; index++ ) levels[ index ] = levels[ index ] || 0;
    return { pages: pages , bookmarks: levels.reduce( ( sum , count ) => sum + count , 0 ) , levels: levels };
  },

  // ---- planning (split_bookmarks.plan_sections) ------------------------------

  plan( marks , level , pageCount , frontMatter ) {
    const starts = [];
    let nowhere = 0;
    let pending = null;
    const collect = ( items ) => {
      for ( const mark of items ) {
        if ( mark.depth >= level || mark.children.length === 0 ) {
          if ( mark.page === null ) {
            nowhere += 1;
            continue;
          }
          const first = pending === null ? mark.page : Math.min( pending , mark.page );
          pending = null;
          starts.push( { first: first , title: mark.title , order: mark.order , mark: mark , last: 0 } );
        } else {
          if ( mark.page !== null ) pending = pending === null ? mark.page : Math.min( pending , mark.page );
          collect( mark.children );
          pending = null;
        }
      }
    };
    collect( marks );
    if ( starts.length === 0 ) return { sections: [] , folded: 0 , nowhere: nowhere };
    starts.sort( ( a , b ) => a.first - b.first || a.order - b.order );
    const kept = [];
    let folded = 0;
    for ( const section of starts ) {
      if ( kept.length && kept[ kept.length - 1 ].first === section.first ) {
        folded += 1;
        continue;
      }
      kept.push( section );
    }
    if ( kept[ 0 ].first > 0 && frontMatter ) {
      kept.unshift( { first: 0 , title: this.FRONT_MATTER , order: 0 , mark: null , last: 0 } );
    }
    kept.forEach( ( section , index ) => {
      section.last = index + 1 < kept.length ? kept[ index + 1 ].first - 1 : pageCount - 1;
    } );
    return { sections: kept , folded: folded , nowhere: nowhere };
  },

  // split_bookmarks.file_name. Python's str.strip(" .") and slicing by code
  // point, not by UTF-16 unit.
  fileName( section , number , width , numbered ) {
    let title = section.title.replace( /[\x00-\x1f/\\:*?"<>|]+/g , " " ).replace( /^[ .]+|[ .]+$/g , "" ) || ( "Section " + number );
    title = Array.from( title.replace( /\s+/g , " " ) ).slice( 0 , this.TITLE_MAX ).join( "" ).trim();
    return numbered ? String( number ).padStart( width , "0" ) + " - " + title + ".pdf" : title + ".pdf";
  },

  // ---- writing a section ----------------------------------------------------

  // Pages first..last (from 0) of source into target, as the server's extract().
  extract( qpdf , source , first , last , target ) {
    qpdf.ok( [ "--empty" , "--pages" , source , ( first + 1 ) + "-" + ( last + 1 ) , "--" , target ] );
  },

  isRef( value ) {
    return typeof value === "string" && /^\d+ \d+ R$/.test( value );
  },

  // The section's own bookmark and those under it, pointed at the new page
  // numbers; a child outside the section's pages is left out (with its own).
  outline( section ) {
    if ( section.mark === null ) return [];
    const item = ( mark ) => {
      if ( mark.page === null || mark.page < section.first || mark.page > section.last ) return null;
      return { title: mark.title , page: mark.page - section.first , children: mark.children.map( item ).filter( Boolean ) };
    };
    return [ { title: section.title , page: 0 , children: section.mark.children.map( item ).filter( Boolean ) } ];
  },

  // Adds the outline and drops links to pages the section no longer has, by
  // writing the changed objects as qpdf JSON and applying them to the file.
  finish( qpdf , section , pagesOnly , target ) {
    const dump = qpdf.json( [ "--json=2" , "--json-key=pages" , "--json-key=qpdf" , "--json-stream-data=none" , pagesOnly ] );
    const header = dump.qpdf[ 0 ];
    const objects = dump.qpdf[ 1 ];
    const value = ( ref ) => {
      const entry = objects[ "obj:" + ref ];
      if ( !entry ) return null;
      return entry.stream ? entry.stream.dict : entry.value;
    };
    const resolve = ( item ) => this.isRef( item ) ? value( item ) : item;
    const pages = dump.pages.map( ( page ) => page.object );
    const inside = new Set( pages );
    const changed = {};

    // split_bookmarks._drop_outside_links
    pages.forEach( ( ref ) => {
      const page = value( ref );
      const annots = resolve( page[ "/Annots" ] );
      if ( !Array.isArray( annots ) ) return;
      const keep = annots.filter( ( annot ) => {
        const dict = resolve( annot );
        if ( !dict || typeof dict !== "object" || Array.isArray( dict ) || dict[ "/Subtype" ] !== "/Link" ) return true;
        let target = resolve( dict[ "/Dest" ] );
        const action = resolve( dict[ "/A" ] );
        if ( target == null && action && typeof action === "object" && action[ "/S" ] === "/GoTo" ) target = resolve( action[ "/D" ] );
        if ( !Array.isArray( target ) || target.length === 0 ) return true;
        const first = target[ 0 ];
        if ( first === null ) return false;
        if ( this.isRef( first ) ) {
          const pointed = value( first );
          if ( pointed === null ) return false;
          if ( typeof pointed === "object" && !Array.isArray( pointed ) && !inside.has( first ) ) return false;
        }
        return true;
      } );
      if ( keep.length !== annots.length ) changed[ "obj:" + ref ] = { value: Object.assign( {} , page , { "/Annots": keep } ) };
    } );

    // The outline, as new objects after the highest the file has.
    let next = header.maxobjectid;
    const make = () => ( ++next ) + " 0 R";
    const tree = this.outline( section );
    if ( tree.length ) {
      const rootRef = objects.trailer.value[ "/Root" ];
      const outlinesRef = make();
      const visible = ( items ) => items.reduce( ( sum , item ) => sum + 1 + visible( item.children ) , 0 );
      const place = ( items , parentRef ) => {
        const refs = items.map( () => make() );
        items.forEach( ( item , index ) => {
          const dict = {
            "/Title": "u:" + item.title,
            "/Parent": parentRef,
            "/Dest": [ pages[ item.page ] , "/Fit" ],
          };
          if ( index > 0 ) dict[ "/Prev" ] = refs[ index - 1 ];
          if ( index + 1 < refs.length ) dict[ "/Next" ] = refs[ index + 1 ];
          if ( item.children.length ) {
            const kids = place( item.children , refs[ index ] );
            dict[ "/First" ] = kids[ 0 ];
            dict[ "/Last" ] = kids[ kids.length - 1 ];
            dict[ "/Count" ] = visible( item.children );
          }
          changed[ "obj:" + refs[ index ] ] = { value: dict };
        } );
        return refs;
      };
      const top = place( tree , outlinesRef );
      changed[ "obj:" + outlinesRef ] = { value: { "/Type": "/Outlines" , "/First": top[ 0 ] , "/Last": top[ top.length - 1 ] , "/Count": visible( tree ) } };
      const root = changed[ "obj:" + rootRef ] ? changed[ "obj:" + rootRef ].value : value( rootRef );
      changed[ "obj:" + rootRef ] = { value: Object.assign( {} , root , { "/Outlines": outlinesRef } ) };
    }

    const update = "/tmp/qpdf-update.json";
    qpdf.write( update , JSON.stringify( { qpdf: [ {
      jsonversion: 2,
      pushedinheritedpageresources: header.pushedinheritedpageresources,
      calledgetallpages: header.calledgetallpages,
      maxobjectid: next,
    } , changed ] } ) );
    try {
      qpdf.ok( [ pagesOnly , "--update-from-json=" + update , "--decode-level=none" , "--object-streams=preserve" , target ] );
    } finally {
      qpdf.remove( update );
    }
  },

  // ---- the whole split -------------------------------------------------------

  // split_bookmarks.run. Sections are written into work. hooks:
  // progress(fraction, name), cancelled(), output(name, path, meta) -- which
  // takes the file away before the next section is written. qpdf.prepare(path)
  // is awaited before each file qpdf writes (see LocalQpdf.prepare).
  async split( qpdf , source , work , options , hooks ) {
    options = Object.assign( {} , this.DEFAULTS , options );
    hooks.progress( 0 , "" );
    const pageCount = this.pageCount( qpdf , source );
    const planned = this.plan( this.marks( qpdf , source , pageCount ) , options.level , pageCount , options.front_matter );
    const sections = planned.sections;
    if ( sections.length === 0 ) throw new Error( "no_bookmarks" );
    const totalPages = sections.reduce( ( sum , section ) => sum + section.last - section.first + 1 , 0 ) || 1;
    const width = Math.max( 2 , String( sections.length ).length );
    let donePages = 0;
    let number = sections[ 0 ].mark !== null ? 1 : 0;
    for ( const section of sections ) {
      if ( hooks.cancelled() ) throw new Error( "cancelled" );
      const name = this.fileName( section , number , width , options.numbered );
      const target = work + "/" + String( number ).padStart( 5 , "0" ) + ".pdf";
      if ( options.inner_bookmarks ) {
        const pagesOnly = work + "/" + String( number ).padStart( 5 , "0" ) + ".pages.pdf";
        await qpdf.prepare( pagesOnly );
        this.extract( qpdf , source , section.first , section.last , pagesOnly );
        try {
          await qpdf.prepare( target );
          this.finish( qpdf , section , pagesOnly , target );
        } finally {
          qpdf.remove( pagesOnly );
        }
      } else {
        await qpdf.prepare( target );
        this.extract( qpdf , source , section.first , section.last , target );
      }
      const pages = section.last - section.first + 1;
      await hooks.output( name , target , { pages: pages , first_page: section.first + 1 , last_page: section.last + 1 , title: section.title } );
      donePages += pages;
      hooks.progress( donePages / totalPages , name );
      number += 1;
    }
    return { sections: sections.length , folded: planned.folded , nowhere: planned.nowhere };
  },
};

// qpdf's command line on a loaded Emscripten module (createQpdf): each call
// runs main once, with what it printed captured.
class LocalQpdf {
  constructor( module , lines ) {
    this.module = module;
    this.lines = lines;
  }

  static async load( createQpdf , extra ) {
    const lines = { out: [] , err: [] };
    const module = await createQpdf( Object.assign( {
      thisProgram: "qpdf",
      print: ( line ) => lines.out.push( line ),
      printErr: ( line ) => lines.err.push( line ),
    } , extra || {} ) );
    return new LocalQpdf( module , lines );
  }

  run( args ) {
    this.lines.out = [];
    this.lines.err = [];
    let code;
    try {
      code = this.module.callMain( args.slice() );
    } catch ( error ) {
      // exit() inside main, or qpdf running out of memory.
      code = error && typeof error.status === "number" ? error.status : 2;
      if ( !( error && typeof error.status === "number" ) ) this.lines.err.push( String( error && error.message || error ) );
    }
    return { code: code , out: this.lines.out.join( "\n" ) , err: this.lines.err.join( "\n" ) };
  }

  // 0 is clean and 3 is done with warnings, which the server's qpdf takes too.
  ok( args ) {
    const answer = this.run( args );
    if ( answer.code !== 0 && answer.code !== 3 ) {
      const error = new Error( "qpdf_failed" );
      error.detail = answer.err;
      throw error;
    }
    return answer;
  }

  // qpdf's JSON, written to a file rather than printed: its logger is one per
  // module and refuses to save to standard output once anything has been
  // printed, which the second call of a module would always hit.
  json( args ) {
    const file = "/tmp/qpdf-answer.json";
    this.ok( args.concat( [ file ] ) );
    try {
      return JSON.parse( this.module.FS.readFile( file , { encoding: "utf8" } ) );
    } finally {
      this.remove( file );
    }
  }

  // Called before qpdf writes path, for a file system that has to open a file
  // ahead of time (OpfsFS, in the worker). Nothing to do anywhere else.
  async prepare( path ) {
    if ( this.preparer ) await this.preparer( path );
  }

  write( path , text ) {
    this.module.FS.writeFile( path , text );
  }

  remove( path ) {
    try { this.module.FS.unlink( path ); } catch ( error ) { /* already gone */ }
  }
}

if ( typeof module !== "undefined" && module.exports ) module.exports = { LocalSplit , LocalQpdf };
