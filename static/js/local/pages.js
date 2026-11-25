// Page lists a person types ("1-3, 7, 10-"), read exactly as the server's
// app/actions/pages.py reads them, plus the shared bits every browser twin
// needs: the name stem, qpdf page ranges, and copying a file through qpdf's
// file system without holding it in memory.
const LocalPages = {
  PART: /^\s*(\d*)\s*(-\s*(\d*))?\s*$/,

  // The pages text names, from 0, in order, each once.
  parse( text , pageCount ) {
    text = String( text || "" ).trim().toLowerCase();
    if ( text === "" || text === "all" ) return Array.from( { length: pageCount } , ( _ , index ) => index );
    const chosen = new Set();
    for ( const part of text.split( "," ) ) {
      if ( !part.trim() ) continue;
      const match = this.PART.exec( part );
      if ( !match || ( !match[ 1 ] && !match[ 3 ] ) ) throw new Error( "bad_pages" );
      const first = match[ 1 ] ? Number( match[ 1 ] ) : 1;
      const last = match[ 2 ] ? ( match[ 3 ] ? Number( match[ 3 ] ) : pageCount ) : first;
      if ( first < 1 || last < first || last > pageCount ) throw new Error( "bad_pages" );
      for ( let page = first - 1 ; page < last ; page++ ) chosen.add( page );
    }
    if ( chosen.size === 0 ) throw new Error( "bad_pages" );
    return Array.from( chosen ).sort( ( a , b ) => a - b );
  },

  // Pages from 0 as qpdf's page ranges, from 1: [0,1,2,6] is "1-3,7".
  ranges( pages ) {
    const parts = [];
    let start = null;
    let previous = null;
    for ( const page of pages ) {
      if ( start === null ) { start = previous = page; continue; }
      if ( page === previous + 1 ) { previous = page; continue; }
      parts.push( start === previous ? String( start + 1 ) : ( start + 1 ) + "-" + ( previous + 1 ) );
      start = previous = page;
    }
    if ( start !== null ) parts.push( start === previous ? String( start + 1 ) : ( start + 1 ) + "-" + ( previous + 1 ) );
    return parts.join( "," );
  },

  stem( name ) {
    const base = String( name || "" ).split( "/" ).pop();
    return base.toLowerCase().endsWith( ".pdf" ) ? base.slice( 0 , -4 ) : ( base || "document" );
  },

  size( qpdf , path ) {
    return qpdf.module.FS.stat( path ).size;
  },

  // source to target in 4 MB pieces, so a large file never sits in memory.
  async copy( qpdf , source , target ) {
    const FS = qpdf.module.FS;
    await qpdf.prepare( target );
    const input = FS.open( source , "r" );
    const output = FS.open( target , "w" );
    const buffer = new Uint8Array( 4 * 1024 * 1024 );
    try {
      let read;
      while ( ( read = FS.read( input , buffer , 0 , buffer.length ) ) > 0 ) FS.write( output , buffer , 0 , read );
    } finally {
      FS.close( input );
      FS.close( output );
    }
  },
};

if ( typeof module !== "undefined" && module.exports ) module.exports = { LocalPages };
