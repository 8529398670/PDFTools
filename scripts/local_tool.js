#!/usr/bin/env node
// Run one browser twin (static/js/local/<tool>.js) under node, on the very
// qpdf.wasm the page loads. Used by scripts/check_local_tools.py to compare
// rotate and compress with the server's; handy on its own too:
//
//   node scripts/local_tool.js rotate book.pdf out/ '{"angle": 180}'
//
// Prints { result , files: [ { name , pages , ... } ] } as JSON.
const fs = require( "fs" );
const path = require( "path" );

const root = path.join( __dirname , ".." );
const local = path.join( root , "static" , "js" , "local" );
const createQpdf = require( path.join( root , "static" , "vendor" , "qpdf" , "qpdf.js" ) );
const { LocalSplit , LocalQpdf } = require( path.join( local , "split_bookmarks.js" ) );
global.LocalSplit = LocalSplit;
global.LocalPages = require( path.join( local , "pages.js" ) ).LocalPages;
const TOOLS = {
  rotate: require( path.join( local , "rotate.js" ) ).LocalRotate,
  compress: require( path.join( local , "compress.js" ) ).LocalCompress,
};

async function main() {
  const [ tool , source , outDir , optionsText ] = process.argv.slice( 2 );
  if ( !TOOLS[ tool ] || !source || !outDir ) {
    console.error( "Usage: node scripts/local_tool.js <" + Object.keys( TOOLS ).join( "|" ) + "> <pdf> <out-dir> [options-json]" );
    process.exit( 2 );
  }
  fs.mkdirSync( outDir , { recursive: true } );
  const qpdf = await LocalQpdf.load( createQpdf );
  const FS = qpdf.module.FS;
  FS.mkdir( "/in" );
  FS.mount( FS.filesystems.NODEFS , { root: path.dirname( path.resolve( source ) ) } , "/in" );
  FS.mkdir( "/work" );
  FS.mount( FS.filesystems.NODEFS , { root: path.resolve( outDir ) } , "/work" );
  const files = [];
  const result = await TOOLS[ tool ].run( qpdf , "/in/" + path.basename( source ) , "/work" , JSON.parse( optionsText || "{}" ) , {
    progress() {},
    cancelled: () => false,
    async output( name , made , meta ) {
      fs.renameSync( path.join( outDir , path.basename( made ) ) , path.join( outDir , name ) );
      files.push( Object.assign( { name: name } , meta ) );
    },
  } , path.basename( source ) );
  console.log( JSON.stringify( { result , files } ) );
}

main().catch( ( error ) => {
  console.error( error.message + ( error.detail ? ": " + error.detail : "" ) );
  process.exit( 1 );
} );
