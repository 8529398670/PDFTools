#!/usr/bin/env node
// Run the browser's split (static/js/local/split_bookmarks.js) under node, on
// the very qpdf.wasm the page loads. Used by scripts/check_local_split.py to
// compare it with the server's split; handy on its own too:
//
//   node scripts/local_split.js book.pdf out/ '{"level": 2}'
//
// Prints { result , files: [ { name , pages , ... } ] } as JSON.
const fs = require( "fs" );
const path = require( "path" );

const root = path.join( __dirname , ".." );
const createQpdf = require( path.join( root , "static" , "vendor" , "qpdf" , "qpdf.js" ) );
const { LocalSplit , LocalQpdf } = require( path.join( root , "static" , "js" , "local" , "split_bookmarks.js" ) );

async function main() {
  const [ source , outDir , optionsText ] = process.argv.slice( 2 );
  if ( !source || !outDir ) {
    console.error( "Usage: node scripts/local_split.js <pdf> <out-dir> [options-json]" );
    process.exit( 2 );
  }
  fs.mkdirSync( outDir , { recursive: true } );
  const qpdf = await LocalQpdf.load( createQpdf );
  const FS = qpdf.module.FS;
  FS.mkdir( "/in" );
  FS.mount( FS.filesystems.NODEFS , { root: path.dirname( path.resolve( source ) ) } , "/in" );
  // Sections are written straight to disk, as the page writes them to OPFS.
  FS.mkdir( "/work" );
  FS.mount( FS.filesystems.NODEFS , { root: path.resolve( outDir ) } , "/work" );
  const files = [];
  const result = await LocalSplit.split( qpdf , "/in/" + path.basename( source ) , "/work" , JSON.parse( optionsText || "{}" ) , {
    progress() {},
    cancelled: () => false,
    async output( name , made , meta ) {
      fs.renameSync( path.join( outDir , path.basename( made ) ) , path.join( outDir , name ) );
      files.push( Object.assign( { name: name } , meta ) );
    },
  } );
  console.log( JSON.stringify( { result , files } ) );
}

main().catch( ( error ) => {
  console.error( error.message + ( error.detail ? ": " + error.detail : "" ) );
  process.exit( 1 );
} );
