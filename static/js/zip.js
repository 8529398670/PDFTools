// A zip made in the browser, for "Download all" on a tool screen that ran on
// this device. Stored, not deflated: a PDF's streams are compressed already.
// The archive is a Blob built from the files' own Blobs, so their bytes are
// read once for the CRC and never copied into memory together.
//
// Plain zip, not zip64: up to 65535 files and 4 GB in all. Zip.fits says
// whether a batch is inside that; past it the page offers "Save all to a
// folder" or one download each.
const Zip = {
  limitBytes: 0xFFFFFFFF - 64 * 1024 * 1024,
  limitFiles: 0xFFFF,

  crcTable: null,

  fits( entries ) {
    const total = entries.reduce( ( sum , entry ) => sum + entry.file.size , 0 );
    return entries.length > 0 && entries.length < this.limitFiles && total < this.limitBytes;
  },

  table() {
    if ( this.crcTable ) return this.crcTable;
    const table = new Uint32Array( 256 );
    for ( let n = 0 ; n < 256 ; n++ ) {
      let c = n;
      for ( let k = 0 ; k < 8 ; k++ ) c = c & 1 ? 0xEDB88320 ^ ( c >>> 1 ) : c >>> 1;
      table[ n ] = c >>> 0;
    }
    this.crcTable = table;
    return table;
  },

  async crc( blob ) {
    const table = this.table();
    let crc = 0xFFFFFFFF;
    const reader = blob.stream().getReader();
    for ( ;; ) {
      const { done , value } = await reader.read();
      if ( done ) break;
      for ( let i = 0 ; i < value.length ; i++ ) crc = table[ ( crc ^ value[ i ] ) & 0xFF ] ^ ( crc >>> 8 );
    }
    return ( crc ^ 0xFFFFFFFF ) >>> 0;
  },

  dosTime( date ) {
    const time = ( date.getHours() << 11 ) | ( date.getMinutes() << 5 ) | ( date.getSeconds() >> 1 );
    const day = ( ( date.getFullYear() - 1980 ) << 9 ) | ( ( date.getMonth() + 1 ) << 5 ) | date.getDate();
    return [ time , day ];
  },

  // entries: [{ name , file }], name may hold "folder/". Answers a Blob.
  // onProgress( done , count ) as each file is read.
  async build( entries , onProgress ) {
    const encoder = new TextEncoder();
    const [ time , day ] = this.dosTime( new Date() );
    const parts = [];
    const central = [];
    const used = new Set();
    let offset = 0;
    for ( let index = 0 ; index < entries.length ; index++ ) {
      const entry = entries[ index ];
      const name = this.unique( entry.name , used );
      const bytes = encoder.encode( name );
      const crc = await this.crc( entry.file );
      const size = entry.file.size;
      const local = new DataView( new ArrayBuffer( 30 ) );
      local.setUint32( 0 , 0x04034b50 , true );
      local.setUint16( 4 , 20 , true );
      local.setUint16( 6 , 0x0800 , true );        // names are UTF-8
      local.setUint16( 8 , 0 , true );             // stored
      local.setUint16( 10 , time , true );
      local.setUint16( 12 , day , true );
      local.setUint32( 14 , crc , true );
      local.setUint32( 18 , size , true );
      local.setUint32( 22 , size , true );
      local.setUint16( 26 , bytes.length , true );
      local.setUint16( 28 , 0 , true );
      parts.push( local.buffer , bytes , entry.file );
      const record = new DataView( new ArrayBuffer( 46 ) );
      record.setUint32( 0 , 0x02014b50 , true );
      record.setUint16( 4 , 20 , true );
      record.setUint16( 6 , 20 , true );
      record.setUint16( 8 , 0x0800 , true );
      record.setUint16( 10 , 0 , true );
      record.setUint16( 12 , time , true );
      record.setUint16( 14 , day , true );
      record.setUint32( 16 , crc , true );
      record.setUint32( 20 , size , true );
      record.setUint32( 24 , size , true );
      record.setUint16( 28 , bytes.length , true );
      record.setUint32( 42 , offset , true );
      central.push( record.buffer , bytes );
      offset += 30 + bytes.length + size;
      if ( onProgress ) onProgress( index + 1 , entries.length );
    }
    const centralSize = central.reduce( ( sum , part ) => sum + part.byteLength , 0 );
    const end = new DataView( new ArrayBuffer( 22 ) );
    end.setUint32( 0 , 0x06054b50 , true );
    end.setUint16( 8 , entries.length , true );
    end.setUint16( 10 , entries.length , true );
    end.setUint32( 12 , centralSize , true );
    end.setUint32( 16 , offset , true );
    return new Blob( [ ...parts , ...central , end.buffer ] , { type: "application/zip" } );
  },

  unique( name , used ) {
    let chosen = name;
    const dot = name.lastIndexOf( "." );
    const stem = dot > name.lastIndexOf( "/" ) ? name.slice( 0 , dot ) : name;
    const suffix = dot > name.lastIndexOf( "/" ) ? name.slice( dot ) : "";
    for ( let counter = 2 ; used.has( chosen.toLowerCase() ) ; counter++ ) chosen = stem + " (" + counter + ")" + suffix;
    used.add( chosen.toLowerCase() );
    return chosen;
  },
};
