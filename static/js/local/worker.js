// The browser's action worker: qpdf (WebAssembly) on files that never leave
// this device. Started by static/js/local.js, one at a time; stopping a run
// is terminating this worker, since qpdf cannot be interrupted mid-call.
//
// Memory stays flat however big the source:
// - the chosen File is mounted with WORKERFS, which hands qpdf slices of it on
//   demand (File.slice + FileReaderSync), so it is never copied in whole;
// - qpdf writes each section straight onto the origin's private disk (OPFS,
//   through OpfsFS in opfs_fs.js), so no section sits in memory either.
//   Without OPFS, sections are written into memory and go back to the page as
//   Blobs, one at a time.
//
// Messages in:  { type: "inspect" , file }
//               { type: "run" , file , steps: [ { action , options } ] , store , batch , job }
//               One step is a tool on its own; more are a chain, each step run
//               on every file the step before made (a split's sections, say).
// Messages out: { type: "info" , info }  { type: "progress" , fraction , name }
//               { type: "output" , name , meta , size , stored: [ job , key ] | blob }
//               (the last step's files only: a chain's in-between files stay
//               on the private disk until the chain ends, then go)
//               { type: "done" , result }  { type: "error" , code , detail }
importScripts( "/vendor/qpdf/qpdf.js" , "/js/local/split_bookmarks.js" , "/js/local/opfs_fs.js" ,
  "/js/local/pages.js" , "/js/local/rotate.js" , "/js/local/compress.js" ,
  "/js/local/wm_core.js" , "/js/local/remove_watermarks.js" );

// Each tool's browser twin, by action name. run( qpdf , source , work ,
// options , hooks , sourceName ) answers the action's result.
const TOOLS = {
  split_bookmarks: ( qpdf , source , work , options , hooks ) => LocalSplit.split( qpdf , source , work , options , hooks ),
  rotate: ( ...args ) => LocalRotate.run( ...args ),
  compress: ( ...args ) => LocalCompress.run( ...args ),
  remove_watermarks: ( ...args ) => LocalWatermarks.run( ...args ),
};

let qpdfReady = null;

function qpdf() {
  if ( !qpdfReady ) {
    qpdfReady = LocalQpdf.load( createQpdf , { locateFile: ( name ) => "/vendor/qpdf/" + name } ).then( ( loaded ) => {
      loaded.module.FS.mkdir( "/in" );
      loaded.module.FS.mkdir( "/work" );
      return loaded;
    } );
  }
  return qpdfReady;
}

// The file at /in/<its name>, for as long as run takes.
async function withFile( file , run ) {
  const loaded = await qpdf();
  const FS = loaded.module.FS;
  FS.mount( FS.filesystems.WORKERFS , { files: [ file ] } , "/in" );
  try {
    return await run( loaded , "/in/" + file.name );
  } finally {
    FS.unmount( "/in" );
  }
}

// The batch's folder on the origin's private disk (local.js clears old ones),
// with a folder of its own for this file, or null where the browser has no
// OPFS sync access (an old browser, a private window).
async function store( message ) {
  try {
    if ( !navigator.storage || !navigator.storage.getDirectory ) return null;
    const root = await navigator.storage.getDirectory();
    const batch = await ( await root.getDirectoryHandle( message.store , { create: true } ) ).getDirectoryHandle( message.batch , { create: true } );
    const folder = await batch.getDirectoryHandle( message.job , { create: true } );
    // Probe that sync handles work here (they need a dedicated worker).
    const probe = await folder.getFileHandle( "probe" , { create: true } );
    const handle = await probe.createSyncAccessHandle();
    handle.close();
    await folder.removeEntry( "probe" );
    return folder;
  } catch ( error ) {
    return null;
  }
}

// A file qpdf wrote into memory, without copying it: Emscripten's in-memory
// file keeps its bytes in a typed array that may be longer than the file.
function bytesOf( FS , path ) {
  const node = FS.lookupPath( path ).node;
  return node.contents ? node.contents.subarray( 0 , node.usedBytes ) : new Uint8Array( 0 );
}

// Every file is written by qpdf straight into the file's OPFS folder
// (OpfsFS), and the page reads the last step's from there. Without OPFS they
// are written into memory and the last step's go back as Blobs.
async function runSteps( message ) {
  const steps = message.steps || [];
  for ( const step of steps ) if ( !TOOLS[ step.action ] ) throw new Error( "unknown_action" );
  const folder = await store( message );
  await withFile( message.file , async ( loaded , source ) => {
    const FS = loaded.module.FS;
    let work = "/work";
    let disk = null;
    if ( folder ) {
      disk = new OpfsFS( FS , folder );
      FS.mkdir( "/out" );
      FS.mount( disk , {} , "/out" );
      work = "/out";
      loaded.preparer = ( path ) => disk.prepare( path );
    }
    // A chain's in-between files, removed when it ends.
    const between = [];
    try {
      let inputs = [ { path: source , name: message.file.name } ];
      const results = [];
      for ( let index = 0 ; index < steps.length ; index++ ) {
        const last = index === steps.length - 1;
        const made = [];
        let stepResult = null;
        for ( let at = 0 ; at < inputs.length ; at++ ) {
          const input = inputs[ at ];
          const share = 1 / steps.length / inputs.length;
          const base = index / steps.length + at * share;
          const hooks = {
            prefix: steps.length > 1 ? "s" + index + "-" + at + "-" : "",
            progress: ( fraction , name ) => postMessage( { type: "progress" , fraction: base + fraction * share , name } ),
            cancelled: () => false,
            async output( name , path , meta ) {
              if ( !last ) {
                made.push( { path: path , name: name } );
                between.push( path );
              } else if ( disk ) {
                const key = await disk.release( path );
                postMessage( { type: "output" , name , meta , stored: [ message.job , key ] , size: disk.root.contents[ key ].size } );
              } else {
                const blob = new Blob( [ bytesOf( FS , path ) ] , { type: "application/pdf" } );
                FS.unlink( path );
                postMessage( { type: "output" , name , meta , blob , size: blob.size } );
              }
            },
          };
          stepResult = await TOOLS[ steps[ index ].action ]( loaded , input.path , work , steps[ index ].options || {} , hooks , input.name );
          if ( index > 0 ) loaded.remove( input.path );
        }
        results.push( stepResult );
        inputs = made;
      }
      postMessage( { type: "done" , result: steps.length === 1 ? results[ 0 ] : { steps: results } } );
    } finally {
      between.forEach( ( path ) => loaded.remove( path ) );
      loaded.preparer = null;
      if ( disk ) {
        await disk.close();
        FS.unmount( "/out" );
        FS.rmdir( "/out" );
      }
    }
  } );
}

self.onmessage = async ( event ) => {
  const message = event.data;
  try {
    if ( message.type === "inspect" ) {
      const info = await withFile( message.file , ( loaded , source ) => LocalSplit.inspect( loaded , source ) );
      postMessage( { type: "info" , info } );
    } else if ( message.type === "run" ) {
      await runSteps( message );
    }
  } catch ( error ) {
    postMessage( { type: "error" , code: error && error.message || "failed" , detail: error && error.detail || "" } );
  }
};
