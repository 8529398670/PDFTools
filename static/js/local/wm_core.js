// Remove watermarks, in the browser: the PDF side of it. A port of
// app/actions/watermarks/{pdfdoc,textmap}.py that reads a PDF through qpdf's
// JSON (qpdf.wasm) instead of pikepdf:
//
// - WmPdf holds every object of the file as qpdf --json=2 gives it, read in
//   two passes: the structure of all objects without stream data, then the
//   decoded data of only the streams that are read (page contents, forms,
//   ToUnicode maps), so a book's pictures are never loaded. Changes are made
//   to those objects in place, each marked with the object it belongs to, and
//   go back with qpdf --update-from-json (remove_watermarks.js).
// - WmContent reads a content stream into instructions and writes them back,
//   keeping each instruction it did not change byte for byte.
// - WmText decodes show-text operands to Unicode and remembers which bytes
//   made each character, so a match can be cut out exactly.
// - WmDocument walks pages and the forms they paint, as pdfdoc.Document.
//
// Where Python's string methods matter (lower, isspace, isalpha, repr, the
// "g" and "%" formats), they are copied here, so the browser reports the same
// findings with the same ids and words as the server
// (scripts/check_local_watermarks.py checks that).
const WmPy = {
  SPACE: /^[\t\n\v\f\r\x1c-\x1f \x85\xa0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]$/,
  ALPHA: /^\p{L}$/u,
  UNPRINTABLE: /^[\p{Cc}\p{Cf}\p{Cs}\p{Co}\p{Cn}\p{Zl}\p{Zp}\p{Zs}]$/u,

  isspace( ch ) { return this.SPACE.test( ch ); },
  isalpha( ch ) { return this.ALPHA.test( ch ); },

  // str.strip() with no argument, or with chars.
  strip( text , chars ) {
    const list = Array.from( text );
    const drop = chars == null ? ( ch ) => this.isspace( ch ) : ( ch ) => chars.includes( ch );
    let start = 0;
    let end = list.length;
    while ( start < end && drop( list[ start ] ) ) start++;
    while ( end > start && drop( list[ end - 1 ] ) ) end--;
    return list.slice( start , end ).join( "" );
  },

  // repr() of a str.
  repr( text ) {
    const chars = Array.from( text );
    const quote = chars.includes( "'" ) && !chars.includes( '"' ) ? '"' : "'";
    let out = quote;
    for ( const ch of chars ) {
      const code = ch.codePointAt( 0 );
      if ( ch === "\\" ) out += "\\\\";
      else if ( ch === quote ) out += "\\" + ch;
      else if ( ch === "\t" ) out += "\\t";
      else if ( ch === "\n" ) out += "\\n";
      else if ( ch === "\r" ) out += "\\r";
      else if ( ch !== " " && this.UNPRINTABLE.test( ch ) ) {
        if ( code < 0x100 ) out += "\\x" + code.toString( 16 ).padStart( 2 , "0" );
        else if ( code < 0x10000 ) out += "\\u" + code.toString( 16 ).padStart( 4 , "0" );
        else out += "\\U" + code.toString( 16 ).padStart( 8 , "0" );
      } else out += ch;
    }
    return out + quote;
  },

  // format( x , "g" ).
  g( x ) {
    if ( x === 0 ) return "0";
    if ( !Number.isFinite( x ) ) return String( x );
    const [ mantissa , exp ] = x.toExponential( 5 ).split( "e" );
    const e = Number( exp );
    const trim = ( s ) => s.includes( "." ) ? s.replace( /0+$/ , "" ).replace( /\.$/ , "" ) : s;
    if ( e >= -4 && e < 6 ) return trim( x.toFixed( Math.max( 0 , 5 - e ) ) );
    return trim( mantissa ) + "e" + ( e < 0 ? "-" : "+" ) + String( Math.abs( e ) ).padStart( 2 , "0" );
  },

  percent( x , digits ) { return ( x * 100 ).toFixed( digits ) + "%"; },

  // round( x , 3 ).
  round3( x ) { return Number( x.toFixed( 3 ) ); },
};

// ---- qpdf JSON objects ---------------------------------------------------------

const WM_REF = /^(\d+) (\d+) R$/;

class WmPdf {
  // dump: qpdf --json=2 with the qpdf and pages keys, no stream data.
  constructor( dump ) {
    this.header = dump.qpdf[ 0 ];
    this.objects = dump.qpdf[ 1 ];
    this.pageRefs = dump.pages.map( ( page ) => page.object );
    this.pageContents = dump.pages.map( ( page ) => page.contents || [] );
    this.next = this.header.maxobjectid;
    this.changed = new Set();
    this.added = {};
    // Every array and dictionary inside an object, to the object it is in:
    // changing one marks that object to be written back.
    this.owner = new WeakMap();
    for ( const [ key , entry ] of Object.entries( this.objects ) ) {
      if ( !key.startsWith( "obj:" ) ) continue;
      const ref = key.slice( 4 );
      this.adopt( entry.stream ? entry.stream.dict : entry.value , ref );
    }
  }

  adopt( value , ref ) {
    if ( value === null || typeof value !== "object" ) return;
    this.owner.set( value , ref );
    for ( const item of Array.isArray( value ) ? value : Object.values( value ) ) this.adopt( item , ref );
  }

  static isRef( value ) { return typeof value === "string" && WM_REF.test( value ); }

  // "12 0" for a reference, the way pikepdf's objgen reads.
  static key( ref ) {
    const match = WM_REF.exec( ref );
    return match ? match[ 1 ] + " " + match[ 2 ] : null;
  }

  entry( ref ) { return this.objects[ "obj:" + ref ] || null; }

  // A reference's object (a stream's dictionary), or value itself.
  resolve( value ) {
    if ( !WmPdf.isRef( value ) ) return value === undefined ? null : value;
    const found = this.entry( value );
    if ( !found ) return null;
    return found.stream ? found.stream.dict : ( found.value === undefined ? null : found.value );
  }

  isStream( value ) {
    const found = WmPdf.isRef( value ) ? this.entry( value ) : null;
    return Boolean( found && found.stream );
  }

  // get_key: container[ key ] resolved, or null. container may be a
  // reference or a dictionary.
  get( container , key ) {
    const dict = this.resolve( container );
    if ( !dict || typeof dict !== "object" || Array.isArray( dict ) ) return null;
    const name = key.startsWith( "/" ) ? key : "/" + key;
    return Object.prototype.hasOwnProperty.call( dict , name ) ? this.resolve( dict[ name ] ) : null;
  }

  // The raw entry: a reference stays a reference.
  raw( container , key ) {
    const dict = this.resolve( container );
    if ( !dict || typeof dict !== "object" || Array.isArray( dict ) ) return null;
    return Object.prototype.hasOwnProperty.call( dict , key ) ? dict[ key ] : null;
  }

  // A stream's decoded bytes, read in the second pass; null when qpdf could
  // not decode it (its dictionary still names a filter) or it was not read.
  data( ref ) {
    const found = this.entry( ref );
    if ( !found || !found.stream || found.stream.data == null ) return null;
    const dict = found.stream.decodedDict || {};
    if ( dict[ "/Filter" ] != null && !( Array.isArray( dict[ "/Filter" ] ) && dict[ "/Filter" ].length === 0 ) ) return null;
    if ( !found.bytes ) found.bytes = WmPdf.unbase64( found.stream.data );
    return found.bytes;
  }

  // Marks the object holding value (a dictionary or array inside one, or a
  // reference) to be written back.
  touch( value ) {
    const ref = WmPdf.isRef( value ) ? value : this.owner.get( value );
    if ( ref ) this.changed.add( ref );
  }

  // New stream data for an existing stream, or a new stream: its reference.
  setData( ref , bytes ) {
    if ( !ref ) {
      ref = ( ++this.next ) + " 0 R";
      this.objects[ "obj:" + ref ] = { stream: { dict: {} } };
      this.added[ ref ] = true;
    }
    const found = this.entry( ref );
    found.bytes = bytes;
    found.rewritten = true;
    found.stream.data = WmPdf.base64( bytes );
    const dict = found.stream.dict || {};
    delete dict[ "/Filter" ];
    delete dict[ "/DecodeParms" ];
    delete dict[ "/Length" ];
    found.stream.dict = dict;
    this.changed.add( ref );
    return ref;
  }

  // The objects changed, as qpdf --update-from-json takes them. A stream
  // whose data did not change goes without it, which leaves its data alone.
  update() {
    const out = {};
    for ( const ref of this.changed ) {
      const found = this.entry( ref );
      if ( !found ) continue;
      if ( found.stream ) {
        const stream = { dict: found.stream.dict || {} };
        if ( found.rewritten ) stream.data = found.stream.data;
        out[ "obj:" + ref ] = { stream };
      } else {
        out[ "obj:" + ref ] = { value: found.value };
      }
    }
    return { qpdf: [ {
      jsonversion: 2,
      pushedinheritedpageresources: this.header.pushedinheritedpageresources,
      calledgetallpages: this.header.calledgetallpages,
      maxobjectid: this.next,
    } , out ] };
  }

  // A text value as Python's str() of a pikepdf object gives it.
  static text( value ) {
    if ( value == null ) return "";
    if ( typeof value === "string" ) {
      if ( value.startsWith( "u:" ) ) return value.slice( 2 );
      if ( value.startsWith( "b:" ) ) {
        const bytes = WmPdf.hex( value.slice( 2 ) );
        return WmText.pdfDoc( bytes );
      }
      return value;
    }
    return String( value );
  }

  static hex( text ) {
    const clean = text.replace( /\s/g , "" );
    const padded = clean.length % 2 ? clean + "0" : clean;
    const out = new Uint8Array( padded.length / 2 );
    for ( let i = 0 ; i < out.length ; i++ ) {
      const byte = parseInt( padded.substr( i * 2 , 2 ) , 16 );
      if ( Number.isNaN( byte ) ) return new Uint8Array( 0 );
      out[ i ] = byte;
    }
    return out;
  }

  static unbase64( text ) {
    const binary = atob( text );
    const out = new Uint8Array( binary.length );
    for ( let i = 0 ; i < binary.length ; i++ ) out[ i ] = binary.charCodeAt( i );
    return out;
  }

  static base64( bytes ) {
    let binary = "";
    for ( let i = 0 ; i < bytes.length ; i += 0x8000 ) binary += String.fromCharCode.apply( null , bytes.subarray( i , i + 0x8000 ) );
    return btoa( binary );
  }
}

// ---- content streams ------------------------------------------------------------

// An operand: { k: "n" , v } a number, { k: "name" , v: "/F1" },
// { k: "str" , v: Uint8Array }, { k: "arr" , v: [ ... ] }, { k: "dict" , v: { } },
// { k: "kw" , v: "true" | "false" | "null" }.
// An instruction: { op , operands , start , end } with its bytes in the
// stream, or { op , operands , raw } when it was made here.
const WmContent = {
  WHITE: new Set( [ 0 , 9 , 10 , 12 , 13 , 32 ] ),
  DELIM: new Set( [ 40 , 41 , 60 , 62 , 91 , 93 , 123 , 125 , 47 , 37 ] ),

  parse( bytes ) {
    const out = [];
    let operands = [];
    let pos = 0;
    let start = -1;
    const n = bytes.length;
    const self = this;

    function skip() {
      while ( pos < n ) {
        const c = bytes[ pos ];
        if ( self.WHITE.has( c ) ) pos++;
        else if ( c === 37 ) { while ( pos < n && bytes[ pos ] !== 10 && bytes[ pos ] !== 13 ) pos++; }
        else break;
      }
    }

    function regular() {
      const from = pos;
      while ( pos < n && !self.WHITE.has( bytes[ pos ] ) && !self.DELIM.has( bytes[ pos ] ) ) pos++;
      return String.fromCharCode.apply( null , bytes.subarray( from , pos ) );
    }

    function literal() {
      pos++;
      const chunk = [];
      let depth = 1;
      while ( pos < n ) {
        let c = bytes[ pos++ ];
        if ( c === 92 ) {
          if ( pos >= n ) break;
          c = bytes[ pos++ ];
          const map = { 110: 10 , 114: 13 , 116: 9 , 98: 8 , 102: 12 , 40: 40 , 41: 41 , 92: 92 };
          if ( map[ c ] !== undefined ) chunk.push( map[ c ] );
          else if ( c >= 48 && c <= 55 ) {
            let value = c - 48;
            for ( let i = 0 ; i < 2 && pos < n && bytes[ pos ] >= 48 && bytes[ pos ] <= 55 ; i++ ) value = value * 8 + bytes[ pos++ ] - 48;
            chunk.push( value & 255 );
          } else if ( c === 13 ) { if ( bytes[ pos ] === 10 ) pos++; }
          else if ( c === 10 ) { /* line continuation */ }
          else chunk.push( c );
        } else if ( c === 40 ) { depth++; chunk.push( c ); }
        else if ( c === 41 ) { depth--; if ( depth === 0 ) break; chunk.push( c ); }
        else if ( c === 13 ) { if ( bytes[ pos ] === 10 ) pos++; chunk.push( 10 ); }
        else chunk.push( c );
      }
      return { k: "str" , v: Uint8Array.from( chunk ) };
    }

    function hexString() {
      pos++;
      let text = "";
      while ( pos < n && bytes[ pos ] !== 62 ) text += String.fromCharCode( bytes[ pos++ ] );
      pos++;
      return { k: "str" , v: WmPdf.hex( text.replace( /[^0-9A-Fa-f]/g , "" ) ) };
    }

    function name() {
      pos++;
      const raw = regular();
      return { k: "name" , v: "/" + raw.replace( /#([0-9A-Fa-f]{2})/g , ( _ , h ) => String.fromCharCode( parseInt( h , 16 ) ) ) };
    }

    function object() {
      skip();
      const c = bytes[ pos ];
      if ( c === 40 ) return literal();
      if ( c === 60 && bytes[ pos + 1 ] === 60 ) {
        pos += 2;
        const dict = {};
        for ( ;; ) {
          skip();
          if ( pos >= n ) break;
          if ( bytes[ pos ] === 62 && bytes[ pos + 1 ] === 62 ) { pos += 2; break; }
          const key = object();
          const value = object();
          if ( key && key.k === "name" ) dict[ key.v ] = value;
        }
        return { k: "dict" , v: dict };
      }
      if ( c === 60 ) return hexString();
      if ( c === 91 ) {
        pos++;
        const items = [];
        for ( ;; ) {
          skip();
          if ( pos >= n ) break;
          if ( bytes[ pos ] === 93 ) { pos++; break; }
          const item = object();
          if ( item === null ) break;
          items.push( item );
        }
        return { k: "arr" , v: items };
      }
      if ( c === 47 ) return name();
      if ( c === 41 || c === 62 || c === 93 || c === 123 || c === 125 ) { pos++; return null; }
      const word = regular();
      if ( word === "" ) { pos++; return null; }
      if ( /^[+-]?(\d+\.?\d*|\.\d+)$/.test( word ) ) return { k: "n" , v: Number( word ) };
      if ( word === "true" || word === "false" || word === "null" ) return { k: "kw" , v: word };
      return { k: "op" , v: word };
    }

    for ( ;; ) {
      skip();
      if ( pos >= n ) break;
      if ( start < 0 ) start = pos;
      const item = object();
      if ( item === null ) continue;
      if ( item.k !== "op" ) {
        operands.push( item );
        continue;
      }
      if ( item.v === "BI" ) {
        // An inline image: its dictionary, ID, binary data, EI. Kept as it is.
        const found = this.inlineEnd( bytes , pos );
        pos = found;
        out.push( { op: "INLINE IMAGE" , operands: [] , start , end: pos } );
      } else {
        out.push( { op: item.v , operands , start , end: pos } );
      }
      operands = [];
      start = -1;
    }
    return out;
  },

  // Where an inline image that starts at from ends (after its EI).
  inlineEnd( bytes , from ) {
    const n = bytes.length;
    let at = from;
    // To ID, the start of the data.
    for ( ; at + 1 < n ; at++ ) {
      if ( bytes[ at ] === 73 && bytes[ at + 1 ] === 68 && this.WHITE.has( bytes[ at - 1 ] ) && ( at + 2 >= n || this.WHITE.has( bytes[ at + 2 ] ) ) ) {
        at += 3;
        break;
      }
    }
    for ( ; at + 1 < n ; at++ ) {
      if ( bytes[ at ] === 69 && bytes[ at + 1 ] === 73 && this.WHITE.has( bytes[ at - 1 ] )
        && ( at + 2 >= n || this.WHITE.has( bytes[ at + 2 ] ) || this.DELIM.has( bytes[ at + 2 ] ) ) ) return at + 2;
    }
    return n;
  },

  // An instruction made here.
  make( op , operands ) { return { op , operands: operands || [] }; },

  num( v ) {
    if ( Number.isInteger( v ) ) return String( v );
    let text = v.toFixed( 6 ).replace( /0+$/ , "" );
    if ( text.endsWith( "." ) ) text = text.slice( 0 , -1 );
    return text === "-0" ? "0" : text;
  },

  operand( item ) {
    switch ( item.k ) {
      case "n": return this.num( item.v );
      case "name": return "/" + item.v.slice( 1 ).replace( /[^!-~]|[#()<>\[\]{}\/%]/g , ( ch ) => "#" + ch.charCodeAt( 0 ).toString( 16 ).padStart( 2 , "0" ) );
      case "str": return "<" + Array.from( item.v , ( b ) => b.toString( 16 ).padStart( 2 , "0" ) ).join( "" ) + ">";
      case "arr": return "[" + item.v.map( ( one ) => this.operand( one ) ).join( " " ) + "]";
      case "dict": return "<<" + Object.entries( item.v ).map( ( [ key , value ] ) => this.operand( { k: "name" , v: key } ) + " " + this.operand( value ) ).join( " " ) + ">>";
      default: return String( item.v );
    }
  },

  // The stream for instructions: each one read from source and not changed
  // keeps its own bytes.
  unparse( instructions , source ) {
    const encoder = new TextEncoder();
    const parts = [];
    let size = 0;
    for ( const instr of instructions ) {
      const piece = instr.start !== undefined && source
        ? source.subarray( instr.start , instr.end )
        : encoder.encode( instr.operands.map( ( item ) => this.operand( item ) ).concat( [ instr.op ] ).join( " " ) );
      parts.push( piece );
      size += piece.length + 1;
    }
    const out = new Uint8Array( size );
    let at = 0;
    for ( const piece of parts ) {
      out.set( piece , at );
      at += piece.length;
      out[ at++ ] = 10;
    }
    return out;
  },
};

// ---- text -----------------------------------------------------------------------------

const WmText = {
  UNKNOWN: "\ufffd",
  SHOW_OPS: new Set( [ "Tj" , "TJ" , "'" , '"' ] ),
  MAX_RANGE: 65536,

  GLYPHS: ( () => {
    const table = {
      space: " ", exclam: "!", quotedbl: '"', numbersign: "#", dollar: "$", percent: "%", ampersand: "&", quotesingle: "'",
      parenleft: "(", parenright: ")", asterisk: "*", plus: "+", comma: ",", hyphen: "-", period: ".", slash: "/",
      zero: "0", one: "1", two: "2", three: "3", four: "4", five: "5", six: "6", seven: "7", eight: "8", nine: "9",
      colon: ":", semicolon: ";", less: "<", equal: "=", greater: ">", question: "?", at: "@",
      bracketleft: "[", backslash: "\\", bracketright: "]", asciicircum: "^", underscore: "_", grave: "`",
      braceleft: "{", bar: "|", braceright: "}", asciitilde: "~",
      quoteleft: "\u2018", quoteright: "\u2019", quotedblleft: "\u201c", quotedblright: "\u201d",
      endash: "\u2013", emdash: "\u2014", bullet: "\u2022",
      fi: "fi", fl: "fl", ff: "ff", ffi: "ffi", ffl: "ffl", dotlessi: "\u0131", germandbls: "\u00df",
      copyright: "\u00a9", registered: "\u00ae", trademark: "\u2122", degree: "\u00b0", endash_: "\u2013", nbspace: "\u00a0",
    };
    for ( let c = 65 ; c <= 90 ; c++ ) {
      table[ String.fromCharCode( c ) ] = String.fromCharCode( c );
      table[ String.fromCharCode( c + 32 ) ] = String.fromCharCode( c + 32 );
    }
    return table;
  } )(),

  // PDFDocEncoding is Latin-1 for what matters here.
  pdfDoc( bytes ) {
    if ( bytes.length >= 2 && bytes[ 0 ] === 0xfe && bytes[ 1 ] === 0xff ) return this.utf16be( bytes.subarray( 2 ) );
    return String.fromCharCode.apply( null , bytes );
  },

  safeChr( value ) {
    if ( value < 0 || value >= 0x110000 || ( value >= 0xd800 && value <= 0xdfff ) ) return null;
    return String.fromCodePoint( value );
  },

  glyph( name ) {
    name = name.replace( /^\/+/ , "" );
    if ( Object.prototype.hasOwnProperty.call( this.GLYPHS , name ) ) return this.GLYPHS[ name ];
    if ( name.includes( "." ) ) return this.glyph( name.split( "." )[ 0 ] );
    let match = /^uni([0-9A-Fa-f]{4,6})$/.exec( name );
    if ( match ) return this.safeChr( parseInt( match[ 1 ] , 16 ) );
    match = /^u([0-9A-Fa-f]{4,6})$/.exec( name );
    if ( match ) return this.safeChr( parseInt( match[ 1 ] , 16 ) );
    if ( name.includes( "_" ) ) {
      const parts = name.split( "_" ).map( ( part ) => this.glyph( part ) );
      if ( parts.every( Boolean ) ) return parts.join( "" );
    }
    return null;
  },

  // bytes.decode( "utf-16-be" , "ignore" ).
  utf16be( bytes ) {
    let out = "";
    for ( let i = 0 ; i + 1 < bytes.length ; i += 2 ) {
      const unit = ( bytes[ i ] << 8 ) | bytes[ i + 1 ];
      if ( unit >= 0xd800 && unit <= 0xdbff ) {
        if ( i + 3 < bytes.length ) {
          const low = ( bytes[ i + 2 ] << 8 ) | bytes[ i + 3 ];
          if ( low >= 0xdc00 && low <= 0xdfff ) {
            out += String.fromCharCode( unit , low );
            i += 2;
          }
        }
        continue;
      }
      if ( unit >= 0xdc00 && unit <= 0xdfff ) continue;
      out += String.fromCharCode( unit );
    }
    return out;
  },

  hexBytes( text ) {
    const clean = text.replace( /\s/g , "" );
    const padded = clean.length % 2 ? clean + "0" : clean;
    if ( !/^[0-9A-Fa-f]*$/.test( padded ) ) return new Uint8Array( 0 );
    return WmPdf.hex( padded );
  },

  big( bytes ) {
    let value = 0;
    for ( const byte of bytes ) value = value * 256 + byte;
    return value;
  },

  // textmap.parse_tounicode, on the CMap's bytes.
  parseToUnicode( bytes ) {
    const data = String.fromCharCode.apply( null , bytes );
    const cmap = new Map();
    const set = ( code , text ) => { if ( !cmap.has( code ) ) cmap.set( code , text ); };
    const hexAll = ( text ) => Array.from( text.matchAll( /<([0-9A-Fa-f\s]*)>/g ) , ( m ) => m[ 1 ] );
    for ( const block of data.matchAll( /beginbfchar([\s\S]*?)endbfchar/g ) ) {
      const toks = hexAll( block[ 1 ] );
      for ( let i = 0 ; i + 1 < toks.length ; i += 2 ) {
        const code = this.hexBytes( toks[ i ] );
        if ( !code.length ) continue;
        set( this.big( code ) , this.utf16be( this.hexBytes( toks[ i + 1 ] ) ) );
      }
    }
    for ( const block of data.matchAll( /beginbfrange([\s\S]*?)endbfrange/g ) ) {
      for ( const m of block[ 1 ].matchAll( /<([0-9A-Fa-f\s]+)>\s*<([0-9A-Fa-f\s]+)>\s*(?:<([0-9A-Fa-f\s]*)>|\[([\s\S]*?)\])/g ) ) {
        const lo = this.big( this.hexBytes( m[ 1 ] ) );
        const hi = this.big( this.hexBytes( m[ 2 ] ) );
        if ( hi < lo || hi - lo > this.MAX_RANGE ) continue;
        if ( m[ 3 ] !== undefined ) {
          const dst = this.hexBytes( m[ 3 ] );
          if ( !dst.length ) continue;
          const base = this.big( dst );
          const prefix = dst.length > 2 ? this.utf16be( dst.subarray( 0 , dst.length - 2 ) ) : "";
          const last = dst.length >= 2 ? this.big( dst.subarray( dst.length - 2 ) ) : base;
          for ( let i = 0 ; i <= hi - lo ; i++ ) {
            const ch = this.safeChr( last + i );
            if ( ch !== null ) set( lo + i , prefix + ch );
          }
        } else {
          hexAll( m[ 4 ] || "" ).forEach( ( tok , i ) => {
            if ( lo + i <= hi ) set( lo + i , this.utf16be( this.hexBytes( tok ) ) );
          } );
        }
      }
    }
    for ( const [ code , text ] of cmap ) if ( !text ) cmap.delete( code );
    return cmap;
  },

  // textmap.load_font.
  font( pdf , name , fontRef ) {
    const info = { name , bytesPerCode: 1 , toUnicode: new Map() , differences: new Map() , baseIsAscii: true , widths: new Map() , defaultWidth: null };
    const font = pdf.resolve( fontRef );
    if ( !font || typeof font !== "object" ) return info;
    const subtype = typeof font[ "/Subtype" ] === "string" ? font[ "/Subtype" ] : "";
    try {
      if ( subtype === "/Type0" ) {
        info.bytesPerCode = 2;
        info.baseIsAscii = false;
        this.cidWidths( pdf , info , pdf.get( font , "/DescendantFonts" ) , pdf.get( font , "/Encoding" ) );
      } else if ( subtype !== "/Type3" ) {
        const first = pdf.get( font , "/FirstChar" );
        const widths = pdf.get( font , "/Widths" );
        if ( first !== null && Array.isArray( widths ) ) {
          const values = widths.map( ( one ) => pdf.resolve( one ) );
          if ( typeof first === "number" && values.every( ( one ) => typeof one === "number" ) ) {
            values.forEach( ( one , offset ) => info.widths.set( Math.trunc( first ) + offset , one ) );
          }
        }
      }
    } catch ( error ) { /* no widths */ }
    const tu = pdf.raw( font , "/ToUnicode" );
    if ( tu && pdf.isStream( tu ) ) {
      const data = pdf.data( tu );
      if ( data && data.length ) info.toUnicode = this.parseToUnicode( data );
    }
    const enc = pdf.get( font , "/Encoding" );
    if ( enc !== null ) {
      const isDict = typeof enc === "object" && !Array.isArray( enc );
      const diffs = isDict ? pdf.get( enc , "/Differences" ) : null;
      if ( Array.isArray( diffs ) ) {
        let current = 0;
        for ( const item of diffs.map( ( one ) => pdf.resolve( one ) ) ) {
          if ( typeof item === "number" ) current = Math.trunc( item );
          else { info.differences.set( current , WmPdf.text( item ) ); current += 1; }
        }
      }
      const base = isDict ? WmPdf.text( pdf.get( enc , "/BaseEncoding" ) || "" ) : ( typeof enc === "string" ? WmPdf.text( enc ) : "" );
      if ( base.includes( "Identity" ) ) info.baseIsAscii = false;
    }
    return info;
  },

  cidWidths( pdf , info , descendants , encoding ) {
    const enc = typeof encoding === "string" ? encoding : "";
    if ( enc.endsWith( "-V" ) || !Array.isArray( descendants ) || !descendants.length ) return;
    const cid = pdf.resolve( descendants[ 0 ] );
    if ( !cid || typeof cid !== "object" ) return;
    const dw = pdf.get( cid , "/DW" );
    info.defaultWidth = typeof dw === "number" ? dw : 1000;
    const w = pdf.get( cid , "/W" );
    const items = Array.isArray( w ) ? w.map( ( one ) => pdf.resolve( one ) ) : [];
    let i = 0;
    while ( i < items.length ) {
      const first = items[ i ];
      const next = items[ i + 1 ];
      if ( typeof first !== "number" ) return;
      if ( Array.isArray( next ) ) {
        next.map( ( one ) => pdf.resolve( one ) ).forEach( ( value , offset ) => info.widths.set( Math.trunc( first ) + offset , value ) );
        i += 2;
      } else if ( typeof next === "number" && typeof items[ i + 2 ] === "number" ) {
        if ( next - first <= this.MAX_RANGE ) for ( let code = Math.trunc( first ) ; code <= Math.trunc( next ) ; code++ ) info.widths.set( code , items[ i + 2 ] );
        i += 3;
      } else return;
    }
  },

  fonts( pdf , resources ) {
    const out = new Map();
    const dict = pdf.get( resources , "/Font" );
    if ( !dict || typeof dict !== "object" || Array.isArray( dict ) ) return out;
    for ( const key of Object.keys( dict ).sort() ) {
      const name = key.replace( /^\/+/ , "" );
      try {
        out.set( name , this.font( pdf , name , dict[ key ] ) );
      } catch ( error ) {
        out.set( name , { name , bytesPerCode: 1 , toUnicode: new Map() , differences: new Map() , baseIsAscii: true , widths: new Map() , defaultWidth: null } );
      }
    }
    return out;
  },

  char( font , code ) {
    if ( font.toUnicode.has( code ) ) return font.toUnicode.get( code );
    if ( font.differences.has( code ) ) {
      const ch = this.glyph( font.differences.get( code ) );
      if ( ch !== null ) return ch;
    }
    if ( font.bytesPerCode === 1 && font.baseIsAscii && code >= 32 && code < 127 ) return String.fromCharCode( code );
    if ( font.bytesPerCode === 1 && font.baseIsAscii && code >= 160 && code < 256 ) return String.fromCharCode( code );
    return this.UNKNOWN;
  },

  width( font , code ) {
    return font.widths.has( code ) ? font.widths.get( code ) : font.defaultWidth;
  },

  FOLD: { "\u2018": "'" , "\u2019": "'" , "\u201a": "'" , "\u201b": "'" , "\u201c": '"' , "\u201d": '"' , "\u201e": '"' ,
    "\u2013": "-" , "\u2014": "-" , "\u2212": "-" , "\u00ad": "-" , "\u00a0": " " , "\u2009": " " , "\u202f": " " , "\u2007": " " },

  // normalize, on a list of characters.
  normalize( chars ) { return chars.map( ( ch ) => this.FOLD[ ch ] || ch ); },

  // squash: lowercased, without spaces, with where each character came from.
  squash( chars ) {
    const out = [];
    const index = [];
    this.normalize( chars ).forEach( ( ch , i ) => {
      if ( WmPy.isspace( ch ) ) return;
      const low = Array.from( ch.toLowerCase() );
      out.push( low.length ? low[ 0 ] : ch );
      index.push( i );
    } );
    return { chars: out , index };
  },

  // textmap.decode_blocks.
  blocks( instructions , fonts ) {
    const blocks = [];
    let chars = [];
    let slots = [];
    let start = -1;
    let current = null;
    let size = 0;
    let tc = 0;
    let tw = 0;
    const self = this;
    const float = ( item , fallback ) => item && item.k === "n" ? item.v : fallback;
    const advance = ( font , code ) => {
      const width = self.width( font , code );
      if ( width === null || width === undefined || !size ) return null;
      const spacing = tc + ( font.bytesPerCode === 1 && code === 32 ? tw : 0 );
      return width + spacing * 1000 / size;
    };
    const plain = ( name ) => ( { name , bytesPerCode: 1 , toUnicode: new Map() , differences: new Map() , baseIsAscii: true , widths: new Map() , defaultWidth: null } );
    const flush = ( end ) => {
      if ( start >= 0 && chars.length ) blocks.push( new WmBlock( chars , slots , start , end ) );
      chars = [];
      slots = [];
      start = -1;
    };
    const decode = ( font , raw , idx , opIdx , aIdx ) => {
      const step = font.bytesPerCode;
      for ( let off = 0 ; off + step <= raw.length ; off += step ) {
        const code = this.big( raw.subarray( off , off + step ) );
        chars.push( this.char( font , code ) );
        slots.push( { instr: idx , operand: opIdx , array: aIdx , start: off , length: step , advance: advance( font , code ) } );
      }
    };
    instructions.forEach( ( instr , idx ) => {
      const op = instr.op;
      const operands = instr.operands;
      if ( op === "BT" ) { flush( idx ); start = idx; return; }
      if ( op === "ET" ) { flush( idx ); return; }
      if ( op === "Tf" ) {
        if ( operands.length ) {
          const fname = operands[ 0 ].k === "name" ? operands[ 0 ].v.replace( /^\/+/ , "" ) : String( operands[ 0 ].v );
          current = fonts.get( fname ) || plain( fname );
          if ( operands.length > 1 ) size = float( operands[ 1 ] , size );
        }
        return;
      }
      if ( op === "Tc" && operands.length ) { tc = float( operands[ 0 ] , tc ); return; }
      if ( op === "Tw" && operands.length ) { tw = float( operands[ 0 ] , tw ); return; }
      if ( op === '"' && operands.length >= 2 ) {
        tw = float( operands[ 0 ] , tw );
        tc = float( operands[ 1 ] , tc );
      }
      if ( !this.SHOW_OPS.has( op ) ) return;
      if ( start < 0 ) start = idx;
      const font = current || plain( "?" );
      if ( op === "TJ" ) {
        const array = operands[ 0 ] && operands[ 0 ].k === "arr" ? operands[ 0 ].v : [];
        array.forEach( ( item , aIdx ) => {
          if ( item.k === "str" ) decode( font , item.v , idx , 0 , aIdx );
        } );
      } else {
        const opIdx = op === '"' ? 2 : 0;
        const item = operands[ opIdx ];
        if ( item && item.k === "str" ) decode( font , item.v , idx , opIdx , -1 );
      }
    } );
    flush( instructions.length );
    return blocks;
  },
};

// textmap.DecodedBlock. chars: what each slot decoded to (a ligature's "fi"
// is one slot); text is them joined, read as code points, as Python does.
class WmBlock {
  constructor( charsOf , slots , start , end ) {
    this.charsOf = charsOf;
    this.slots = slots;
    this.startInstr = start;
    this.endInstr = end;
    this.chars = [];
    this.charSlot = [];
    charsOf.forEach( ( text , slot ) => {
      for ( const ch of Array.from( text ) ) {
        this.chars.push( ch );
        this.charSlot.push( slot );
      }
    } );
    this.text = this.chars.join( "" );
    const squashed = WmText.squash( this.chars );
    this.squashed = squashed.chars;
    this.map = squashed.index;
  }

  slotSpan( start , end ) {
    if ( end <= start || start >= this.charSlot.length ) return [ 0 , 0 ];
    return [ this.charSlot[ start ] , this.charSlot[ Math.min( end , this.charSlot.length ) - 1 ] + 1 ];
  }

  atBoundary( start , end ) {
    const before = start > 0 ? this.squashed[ start - 1 ] : "";
    const after = end < this.squashed.length ? this.squashed[ end ] : "";
    return !( ( before && WmPy.isalpha( before ) ) || ( after && WmPy.isalpha( after ) ) );
  }

  search( needle , boundary ) {
    const key = WmText.squash( Array.from( needle ) ).chars;
    if ( !key.length ) return [];
    const hay = this.squashed;
    const hits = [];
    for ( let at = 0 ; at + key.length <= hay.length ; ) {
      let same = true;
      for ( let j = 0 ; j < key.length ; j++ ) if ( hay[ at + j ] !== key[ j ] ) { same = false; break; }
      if ( !same ) { at++; continue; }
      if ( !boundary || this.atBoundary( at , at + key.length ) ) hits.push( [ at , at + key.length ] );
      at += key.length;
    }
    return this.spans( hits );
  }

  // A regular expression on the text as it reads, ignoring case. Indices
  // are in code points, as Python's.
  searchRegex( pattern ) {
    let rx;
    try { rx = new RegExp( pattern , "giu" ); } catch ( error ) {
      try { rx = new RegExp( pattern , "gi" ); } catch ( again ) { return []; }
    }
    const text = WmText.normalize( this.chars ).join( "" );
    const toPoint = [];
    let point = 0;
    for ( let unit = 0 ; unit < text.length ; ) {
      const width = text.codePointAt( unit ) > 0xffff ? 2 : 1;
      for ( let k = 0 ; k < width ; k++ ) toPoint[ unit + k ] = point;
      unit += width;
      point += 1;
    }
    toPoint[ text.length ] = point;
    const out = [];
    for ( const m of text.matchAll( rx ) ) {
      if ( m[ 0 ].length === 0 ) continue;
      out.push( [ toPoint[ m.index ] , toPoint[ m.index + m[ 0 ].length ] ] );
    }
    return out;
  }

  spans( pairs ) {
    const out = [];
    for ( const [ s , e ] of pairs ) {
      if ( e <= s || e > this.map.length ) continue;
      out.push( [ this.map[ s ] , this.map[ e - 1 ] + 1 ] );
    }
    return out;
  }
}

// ---- the document ---------------------------------------------------------------------

const WM_IDENTITY = [ 1 , 0 , 0 , 1 , 0 , 0 ];

const WmMatrix = {
  mul( m , c ) {
    const [ a1 , b1 , c1 , d1 , e1 , f1 ] = m;
    const [ a2 , b2 , c2 , d2 , e2 , f2 ] = c;
    return [ a1 * a2 + b1 * c2 , a1 * b2 + b1 * d2 , c1 * a2 + d1 * c2 , c1 * b2 + d1 * d2 , e1 * a2 + f1 * c2 + e2 , e1 * b2 + f1 * d2 + f2 ];
  },
  rotated( m , tol ) {
    tol = tol === undefined ? 1e-3 : tol;
    return Math.abs( m[ 1 ] ) > tol || Math.abs( m[ 2 ] ) > tol;
  },
};

// pdfdoc.Scope: one content stream. key is the stream's "n g", or
// "page n g" for a page whose contents are several streams (or none).
class WmScope {
  constructor( pdf , key , ref , pageRef , instructions , source , resources , depth , isPage ) {
    this.pdf = pdf;
    this.key = key;
    this.ref = ref;
    this.pageRef = pageRef;
    this.instructions = instructions;
    this.source = source;
    this.resources = resources;
    this.pages = new Set();
    this.depth = depth;
    this.isPage = isPage;
    this.dirty = false;
    this._fonts = null;
    this._blocks = null;
  }

  get fonts() {
    if ( !this._fonts ) this._fonts = WmText.fonts( this.pdf , this.resources );
    return this._fonts;
  }

  get blocks() {
    if ( !this._blocks ) this._blocks = WmText.blocks( this.instructions , this.fonts );
    return this._blocks;
  }

  get text() { return this.blocks.map( ( block ) => block.text ).join( "" ); }

  invalidate() { this._blocks = null; }

  // Back into the PDF (in memory): a stream gets its new data; a page whose
  // contents were several streams gets one new stream in their place.
  writeBack( doc ) {
    const data = WmContent.unparse( this.instructions , this.source );
    if ( this.ref ) {
      this.pdf.setData( this.ref , data );
    } else {
      const ref = this.pdf.setData( null , data );
      for ( const pindex of this.pages ) {
        const page = this.pdf.resolve( this.pdf.pageRefs[ pindex ] );
        page[ "/Contents" ] = ref;
        this.pdf.touch( this.pdf.pageRefs[ pindex ] );
      }
    }
    this.dirty = false;
  }
}

class WmDocument {
  constructor( pdf ) {
    this.pdf = pdf;
    this.scopes = new Map();
    this.invocations = [];
    // Direct objects have no number; they are told apart by identity.
    this.ids = new WeakMap();
    this.nextId = 0;
    this.walk();
  }

  get pageCount() { return this.pdf.pageRefs.length; }

  // objkey: "n g" for an object with a number, else one made up for it.
  objkey( value , ref ) {
    if ( ref && WmPdf.isRef( ref ) ) return WmPdf.key( ref );
    if ( value === null || typeof value !== "object" ) return "direct " + String( value );
    if ( !this.ids.has( value ) ) this.ids.set( value , "direct #" + ( ++this.nextId ) );
    return this.ids.get( value );
  }

  // A page's content: its streams' decoded data, one after another.
  pageData( pindex ) {
    const refs = this.pdf.pageContents[ pindex ];
    const parts = [];
    for ( const ref of refs ) {
      const data = this.pdf.data( ref );
      if ( data === null ) return null;
      parts.push( data );
    }
    let size = parts.reduce( ( sum , part ) => sum + part.length + 1 , 0 );
    const out = new Uint8Array( size );
    let at = 0;
    for ( const part of parts ) {
      out.set( part , at );
      at += part.length;
      out[ at++ ] = 10;
    }
    return out;
  }

  walk() {
    this.pdf.pageRefs.forEach( ( pageRef , pindex ) => {
      const page = this.pdf.resolve( pageRef );
      const data = this.pageData( pindex );
      if ( data === null ) return;
      let instructions;
      try { instructions = WmContent.parse( data ); } catch ( error ) { return; }
      const contents = page[ "/Contents" ];
      const single = WmPdf.isRef( contents ) && this.pdf.isStream( contents );
      const key = single ? WmPdf.key( contents ) : "page " + WmPdf.key( pageRef );
      const resources = this.pdf.get( page , "/Resources" );
      const scope = this.scope( key , single ? contents : null , pageRef , instructions , data , resources , this.objkey( resources , page[ "/Resources" ] ) , 0 , true );
      scope.pages.add( pindex );
      this.descend( scope , pindex , WM_IDENTITY , 0 , new Set() , { order: 0 } );
    } );
  }

  scope( key , ref , pageRef , instructions , source , resources , resourcesKey , depth , isPage ) {
    const existing = this.scopes.get( key );
    if ( existing ) {
      existing.depth = Math.min( existing.depth , depth );
      return existing;
    }
    const made = new WmScope( this.pdf , key , ref , pageRef , instructions , source , resources , depth , isPage );
    // Which /Resources it uses, as remove's resource dropping compares them.
    made.resourcesKey = resourcesKey;
    this.scopes.set( key , made );
    return made;
  }

  descend( scope , pindex , base , depth , seen , counter ) {
    if ( depth > 12 ) return;
    const pdf = this.pdf;
    const xobjects = pdf.get( scope.resources , "/XObject" );
    const gstates = pdf.get( scope.resources , "/ExtGState" );
    let ctm = base;
    const stack = [];
    let alpha = 1;
    const alphas = [];
    const num = ( item , fallback ) => item && item.k === "n" ? item.v : fallback;

    scope.instructions.forEach( ( instr , idx ) => {
      const op = instr.op;
      const operands = instr.operands;
      if ( op === "q" ) {
        stack.push( ctm );
        alphas.push( alpha );
      } else if ( op === "Q" ) {
        if ( stack.length ) ctm = stack.pop();
        if ( alphas.length ) alpha = alphas.pop();
      } else if ( op === "cm" && operands.length >= 6 ) {
        ctm = WmMatrix.mul( operands.slice( 0 , 6 ).map( ( one ) => num( one , 0 ) ) , ctm );
      } else if ( op === "gs" && operands.length && gstates !== null ) {
        const gs = pdf.get( gstates , WmDocument.nameOf( operands[ 0 ] ) );
        if ( gs !== null ) {
          const ca = pdf.get( gs , "/ca" );
          if ( ca !== null ) alpha = typeof ca === "number" ? ca : 1;
        }
      } else if ( op === "Do" && operands.length && xobjects !== null ) {
        const name = WmDocument.nameOf( operands[ 0 ] );
        const targetRef = pdf.raw( xobjects , name.startsWith( "/" ) ? name : "/" + name );
        const target = pdf.resolve( targetRef );
        if ( target === null ) return;
        const subtype = WmPdf.text( pdf.get( target , "/Subtype" ) || "" );
        const tkey = this.objkey( target , targetRef );
        this.invocations.push( {
          name: name.replace( /^\/+/ , "" ), target: tkey , targetRef , obj: target , subtype: subtype.replace( /^\/+/ , "" ),
          page: pindex , ctm , order: counter.order , alpha , scope: scope.key , instr: idx , depth ,
        } );
        counter.order += 1;
        if ( subtype === "/Form" ) {
          if ( seen.has( tkey ) ) return;
          const data = pdf.data( targetRef );
          if ( data === null ) return;
          let sub;
          try { sub = WmContent.parse( data ); } catch ( error ) { return; }
          const own = pdf.get( target , "/Resources" );
          const child = this.scope( tkey , targetRef , null , sub , data , own !== null ? own : scope.resources ,
            own !== null ? this.objkey( own , pdf.raw( target , "/Resources" ) ) : scope.resourcesKey , depth + 1 , false );
          child.pages.add( pindex );
          let formCtm = ctm;
          const matrix = pdf.get( target , "/Matrix" );
          if ( Array.isArray( matrix ) && matrix.length >= 6 ) {
            formCtm = WmMatrix.mul( matrix.slice( 0 , 6 ).map( ( one ) => typeof pdf.resolve( one ) === "number" ? pdf.resolve( one ) : 0 ) , ctm );
          }
          this.descend( child , pindex , formCtm , depth + 1 , new Set( [ ...seen , tkey ] ) , counter );
        }
      }
    } );
  }

  static nameOf( item ) {
    if ( !item ) return "";
    if ( item.k === "name" ) return item.v;
    return String( item.v );
  }

  pageBox( pindex ) {
    const page = this.pdf.resolve( this.pdf.pageRefs[ pindex ] );
    for ( const key of [ "/CropBox" , "/MediaBox" ] ) {
      const box = this.pdf.get( page , key );
      if ( Array.isArray( box ) && box.length >= 4 ) {
        const [ x0 , y0 , x1 , y1 ] = box.slice( 0 , 4 ).map( ( one ) => this.pdf.resolve( one ) );
        if ( [ x0 , y0 , x1 , y1 ].every( ( one ) => typeof one === "number" ) ) {
          return [ Math.min( x0 , x1 ) , Math.min( y0 , y1 ) , Math.max( x0 , x1 ) , Math.max( y0 , y1 ) ];
        }
      }
    }
    return [ 0 , 0 , 612 , 792 ];
  }

  writeBack() {
    for ( const scope of this.scopes.values() ) if ( scope.dirty ) scope.writeBack( this );
  }
}

if ( typeof module !== "undefined" && module.exports ) {
  module.exports = { WmPy , WmPdf , WmContent , WmText , WmBlock , WmMatrix , WmScope , WmDocument , WM_IDENTITY };
}
