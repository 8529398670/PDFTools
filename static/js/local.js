// Split on this device: the Library card that splits PDFs in the browser, with
// qpdf compiled to WebAssembly (js/local/worker.js runs it; the split itself is
// js/local/split_bookmarks.js, the same split as the server's). The PDFs are
// never uploaded: the sections are saved straight from this page.
//
// Where splits run is this device's own choice, kept in localStorage:
// - Automatic: this device if it looks up to it (WebAssembly and workers, at
//   least 4 cores, and at least 4 GB where the browser says), else the server;
// - This device: always here, if the browser can at all;
// - The server: PDFs picked here are imported into the library instead.
//
// Results land in the origin's private disk (OPFS) under a folder per batch,
// so a run of large sections never sits in memory. Folders older than a day
// are cleared when the page loads.
const Local = {
  prefKey: "pdftools-engine.split_bookmarks",
  store: "pdftools-local",
  keepHours: 24,
  minCores: 4,
  minMemory: 4,
  worker: null,
  pending: null,
  jobs: [],
  running: false,
  cancelled: false,
  urls: [],

  init( me ) {
    if ( me.files_enabled === false ) return;
    const card = Dom.get( "local-card" );
    Dom.show( card , true );
    const select = Dom.get( "local-engine" );
    select.value = this.preference();
    select.addEventListener( "change" , () => {
      try { window.localStorage.setItem( this.prefKey , select.value ); } catch ( error ) { /* private mode */ }
      this.paintEngine();
    } );
    const input = Dom.get( "local-pick" );
    Dom.get( "local-pick-button" ).addEventListener( "click" , () => input.click() );
    input.addEventListener( "change" , () => {
      const files = Array.from( input.files );
      input.value = "";
      this.picked( files );
    } );
    Dom.onPress( Dom.get( "local-cancel" ) , () => this.cancel() );
    Dom.onPress( Dom.get( "local-download-all" ) , () => this.downloadAll() );
    Dom.onPress( Dom.get( "local-save-folder" ) , () => this.saveToFolder() );
    this.watchDrops( card );
    window.addEventListener( "beforeunload" , ( event ) => {
      if ( this.running ) event.preventDefault();
    } );
    if ( typeof Fresh !== "undefined" && Fresh.holdWhile ) Fresh.holdWhile( () => this.running );
    this.paintEngine();
    this.sweep();
  },

  // ---- where it runs ---------------------------------------------------------

  preference() {
    let value = "auto";
    try { value = window.localStorage.getItem( this.prefKey ) || "auto"; } catch ( error ) { /* private mode */ }
    return [ "auto" , "device" , "server" ].includes( value ) ? value : "auto";
  },

  // What this device has. deviceMemory is Chromium's, rounded and capped at 8;
  // where it is missing, memory is not held against the device.
  device() {
    const supported = typeof WebAssembly === "object" && typeof Worker === "function" && typeof Blob === "function";
    const cores = navigator.hardwareConcurrency || 1;
    const memory = typeof navigator.deviceMemory === "number" ? navigator.deviceMemory : null;
    const capable = supported && cores >= this.minCores && ( memory === null || memory >= this.minMemory );
    return { supported , cores , memory , capable };
  },

  engine() {
    const device = this.device();
    const preference = this.preference();
    if ( !device.supported || preference === "server" ) return "server";
    if ( preference === "device" ) return "device";
    return device.capable ? "device" : "server";
  },

  paintEngine() {
    const device = this.device();
    const preference = this.preference();
    const memory = device.memory === null ? "" : I18n.get( "local.memory" ).replace( "{gb}" , device.memory );
    let help;
    if ( !device.supported ) help = I18n.get( "local.unsupported" );
    else if ( preference === "auto" ) help = I18n.get( device.capable ? "local.auto_device" : "local.auto_server" ).replace( "{cores}" , device.cores ).replace( "{memory}" , memory );
    else help = I18n.get( preference === "device" ? "local.device_help" : "local.server_help" );
    Dom.text( Dom.get( "local-engine-help" ) , help );
    const here = this.engine() === "device";
    Dom.text( Dom.get( "local-pick-text" ) , I18n.get( here ? "local.pick_device" : "local.pick_server" ) );
    Dom.get( "local-pick-icon" ).className = "bi me-1 " + ( here ? "bi-cpu" : "bi-cloud-arrow-up" );
    Dom.get( "local-pick-button" ).disabled = this.running;
  },

  // ---- choosing ----------------------------------------------------------------

  // A drop on this card is the card's, not the Library's import (which takes
  // drops anywhere else on the screen).
  watchDrops( card ) {
    const carriesFiles = ( event ) => Array.from( event.dataTransfer.types ).includes( "Files" );
    [ "dragenter" , "dragover" ].forEach( ( name ) => card.addEventListener( name , ( event ) => {
      if ( !carriesFiles( event ) ) return;
      event.preventDefault();
      event.stopPropagation();
      card.classList.add( "file-drop-active" );
    } ) );
    card.addEventListener( "dragleave" , ( event ) => {
      if ( !card.contains( event.relatedTarget ) ) card.classList.remove( "file-drop-active" );
    } );
    card.addEventListener( "drop" , ( event ) => {
      if ( !carriesFiles( event ) ) return;
      event.preventDefault();
      event.stopPropagation();
      card.classList.remove( "file-drop-active" );
      this.picked( Array.from( event.dataTransfer.files ) );
    } );
  },

  picked( files ) {
    const pdfs = files.filter( ( file ) => Library.isPdf( file ) );
    const skipped = files.length - pdfs.length;
    if ( skipped > 0 ) Dom.toast( I18n.get( "library.skipped" ).replace( "{count}" , skipped ) , "error" );
    if ( pdfs.length === 0 ) return;
    if ( this.engine() === "server" ) {
      Library.enqueue( pdfs.map( ( file ) => ( { file: file , folder: "" } ) ) );
      Dom.toast( I18n.get( "local.imported_for_server" ).replace( "{count}" , pdfs.length ) , "ok" );
      return;
    }
    if ( this.running ) return;
    this.start( pdfs );
  },

  // ---- the worker -------------------------------------------------------------

  // One message to the worker, answered by its "info" or "done"; on the way,
  // each other message goes to onEvent.
  call( message , onEvent ) {
    if ( !this.worker ) this.worker = new Worker( "/js/local/worker.js" );
    return new Promise( ( resolve , reject ) => {
      this.pending = { reject };
      this.worker.onmessage = ( event ) => {
        const data = event.data;
        if ( data.type === "info" ) resolve( data.info );
        else if ( data.type === "done" ) resolve( data.result );
        else if ( data.type === "error" ) {
          // qpdf may have aborted, which leaves its module unusable: start
          // the next file on a fresh worker.
          this.dropWorker();
          const error = new Error( /OOM|memory/i.test( data.detail || "" ) ? "memory" : data.code );
          error.detail = data.detail;
          reject( error );
        } else if ( onEvent ) onEvent( data );
      };
      this.worker.onerror = ( event ) => {
        event.preventDefault();
        this.dropWorker();
        const error = new Error( /memory/i.test( event.message || "" ) ? "memory" : "failed" );
        error.detail = event.message || "";
        reject( error );
      };
      this.worker.postMessage( message );
    } );
  },

  dropWorker() {
    if ( this.worker ) this.worker.terminate();
    this.worker = null;
  },

  cancel() {
    this.cancelled = true;
    this.dropWorker();
    if ( this.pending ) this.pending.reject( new Error( "cancelled" ) );
  },

  // ---- a batch ---------------------------------------------------------------

  async start( files ) {
    this.urls.forEach( ( url ) => URL.revokeObjectURL( url ) );
    this.urls = [];
    this.cancelled = false;
    this.running = true;
    this.batchId = Date.now() + "-" + Math.random().toString( 36 ).slice( 2 , 8 );
    this.jobs = files.map( ( file ) => ( { file , state: "reading" , outputs: [] , fraction: 0 , name: "" } ) );
    Dom.swap( Dom.get( "local-list" ) , ...this.jobs.map( ( job ) => this.jobRow( job ) ) );
    Dom.show( Dom.get( "local-batch" ) , true );
    this.paintEngine();
    this.paintBatch();
    try {
      await this.inspectAll();
      const ready = this.jobs.filter( ( job ) => job.state === "waiting" );
      const options = ready.length && !this.cancelled ? await this.askOptions( ready ) : null;
      if ( !options ) {
        ready.forEach( ( job ) => this.setState( job , "cancelled" ) );
      } else {
        for ( const job of ready ) {
          if ( this.cancelled ) this.setState( job , "cancelled" );
          else await this.splitOne( job , options );
        }
      }
    } finally {
      this.running = false;
      this.pending = null;
      this.paintEngine();
      this.paintBatch();
    }
  },

  async inspectAll() {
    for ( const job of this.jobs ) {
      if ( this.cancelled ) {
        this.setState( job , "cancelled" );
        continue;
      }
      try {
        job.info = await this.call( { type: "inspect" , file: job.file } );
        if ( job.info.bookmarks === 0 ) this.setState( job , "failed" , "no_bookmarks" );
        else this.setState( job , "waiting" );
      } catch ( error ) {
        this.setState( job , this.cancelled ? "cancelled" : "failed" , error.message );
      }
    }
  },

  // The same dialog as the server's split (library.js), answering the options.
  async askOptions( jobs ) {
    const depth = Math.max( ...jobs.map( ( job ) => job.info.levels.length ) );
    const levels = Array.from( { length: depth } , ( unused , index ) => {
      const label = I18n.get( "split.level_option" ).replace( "{level}" , index + 1 );
      const counts = jobs.length === 1 ? I18n.get( "split.level_count" ).replace( "{count}" , jobs[ 0 ].info.levels[ index ] ) : "";
      return { value: String( index + 1 ) , label: label + counts };
    } );
    const title = jobs.length === 1
      ? I18n.get( "split.title_one" ).replace( "{name}" , jobs[ 0 ].file.name )
      : I18n.get( "split.title_many" ).replace( "{count}" , jobs.length );
    let chosen = null;
    const answered = await Dom.form( {
      title: title,
      submit: I18n.get( "split.start" ),
      fields: [
        { name: "level" , label: I18n.get( "split.level" ) , type: "select" , options: levels , value: "1" , help: I18n.get( "split.level_help" ) },
        { name: "front_matter" , label: I18n.get( "split.front_matter" ) , type: "checkbox" , value: true },
        { name: "inner_bookmarks" , label: I18n.get( "split.inner_bookmarks" ) , type: "checkbox" , value: true },
        { name: "numbered" , label: I18n.get( "split.numbered" ) , type: "checkbox" , value: true },
      ],
      save: ( values ) => { chosen = Object.assign( {} , values , { level: Number( values.level ) } ); },
    } );
    return answered ? chosen : null;
  },

  async splitOne( job , options ) {
    this.setState( job , "splitting" );
    try {
      const index = this.jobs.indexOf( job );
      job.result = await this.call( { type: "split" , file: job.file , options: options , store: this.store , batch: this.batchId , job: "file-" + index } , async ( data ) => {
        if ( data.type === "progress" ) {
          job.fraction = data.fraction;
          job.name = data.name;
          this.paintJob( job );
        } else if ( data.type === "output" ) {
          const file = data.stored ? await this.storedFile( data.stored ) : data.blob;
          const url = URL.createObjectURL( file );
          this.urls.push( url );
          job.outputs.push( { name: data.name , meta: data.meta , size: data.size , file , url } );
          this.paintJob( job );
        }
      } );
      this.setState( job , "done" );
    } catch ( error ) {
      this.setState( job , this.cancelled ? "cancelled" : "failed" , error.message );
    }
  },

  async storedFile( [ job , key ] ) {
    const root = await navigator.storage.getDirectory();
    const batch = await ( await root.getDirectoryHandle( this.store ) ).getDirectoryHandle( this.batchId );
    return ( await ( await batch.getDirectoryHandle( job ) ).getFileHandle( key ) ).getFile();
  },

  // Clears batch folders older than keepHours, from earlier visits.
  async sweep() {
    try {
      if ( !navigator.storage || !navigator.storage.getDirectory ) return;
      const root = await navigator.storage.getDirectory();
      const folder = await root.getDirectoryHandle( this.store , { create: true } );
      const old = Date.now() - this.keepHours * 3600 * 1000;
      for await ( const [ name ] of folder.entries() ) {
        if ( Number( name.split( "-" )[ 0 ] ) < old ) await folder.removeEntry( name , { recursive: true } ).catch( () => {} );
      }
    } catch ( error ) { /* nothing to clear */ }
  },

  // ---- saving ----------------------------------------------------------------

  outputs() {
    return this.jobs.flatMap( ( job ) => job.outputs.map( ( output ) => Object.assign( { job } , output ) ) );
  },

  // One download each; the browser may ask once whether this page may save
  // several files.
  async downloadAll() {
    for ( const output of this.outputs() ) {
      const link = Dom.el( "a" , { attrs: { href: output.url , download: output.name } } );
      document.body.appendChild( link );
      link.click();
      link.remove();
      await new Promise( ( resolve ) => setTimeout( resolve , 300 ) );
    }
  },

  // Every section into a folder the person picks, streamed from disk to disk;
  // with several PDFs, each gets a folder of its own named after it.
  async saveToFolder() {
    let target;
    try {
      target = await window.showDirectoryPicker( { mode: "readwrite" } );
    } catch ( error ) {
      return;
    }
    const several = this.jobs.filter( ( job ) => job.outputs.length ).length > 1;
    let count = 0;
    try {
      for ( const job of this.jobs ) {
        if ( !job.outputs.length ) continue;
        const folder = several ? await target.getDirectoryHandle( job.file.name.replace( /\.pdf$/i , "" ) , { create: true } ) : target;
        for ( const output of job.outputs ) {
          const writable = await ( await folder.getFileHandle( output.name , { create: true } ) ).createWritable();
          await output.file.stream().pipeTo( writable );
          count += 1;
        }
      }
      Dom.toast( I18n.get( "local.saved_folder" ).replace( "{count}" , count ).replace( "{folder}" , target.name ) , "ok" );
    } catch ( error ) {
      App.showError( error.message );
    }
  },

  // ---- showing -----------------------------------------------------------------

  setState( job , state , reason ) {
    job.state = state;
    job.reason = reason || "";
    this.paintJob( job );
    this.paintBatch();
  },

  jobRow( job ) {
    const name = Dom.el( "span" , { class: "text-break flex-grow-1 fw-medium" , text: job.file.name } );
    const status = Dom.el( "span" , { class: "text-body-secondary text-nowrap" } );
    const bar = Dom.el( "progress" , { class: "w-100" , attrs: { max: "1" , value: "0" , "aria-label": job.file.name } } );
    const note = Dom.el( "div" , { class: "text-body-secondary" } );
    const list = Dom.el( "ul" , { class: "list-unstyled mb-0 mt-1" } );
    const summary = Dom.el( "summary" , { class: "text-body-secondary" } );
    const details = Dom.el( "details" , { class: "mt-1" , children: [ summary , list ] } );
    const element = Dom.el( "li" , { class: "list-group-item px-0" , children: [
      Dom.el( "div" , { class: "d-flex flex-wrap gap-2" , children: [ name , status ] } ),
      bar, note, details,
    ] } );
    job.row = { element , status , bar , note , list , summary , details , shown: 0 };
    this.paintJob( job );
    return element;
  },

  paintJob( job ) {
    const row = job.row;
    if ( !row ) return;
    const size = job.outputs.reduce( ( sum , output ) => sum + output.size , 0 );
    const words = {
      reading: I18n.get( "local.reading" ),
      waiting: I18n.get( "local.waiting" ),
      splitting: I18n.get( "local.splitting" ).replace( "{percent}" , Math.floor( job.fraction * 100 ) ).replace( "{name}" , job.name || job.file.name ),
      done: I18n.get( "local.done" ).replace( "{count}" , job.outputs.length ).replace( "{size}" , Files.size( size ) ),
      failed: I18n.get( "local.failed" ).replace( "{reason}" , I18n.get( "local.errors." + job.reason ) || job.reason ),
      cancelled: I18n.get( "local.cancelled" ),
    };
    Dom.text( row.status , words[ job.state ] );
    row.status.className = "text-nowrap " + ( job.state === "failed" ? "text-danger" : job.state === "done" ? "text-success" : "text-body-secondary" );
    row.bar.value = job.state === "done" ? 1 : job.fraction;
    Dom.show( row.bar , job.state === "splitting" );
    const notes = [];
    if ( job.result && job.result.folded ) notes.push( I18n.get( "local.folded" ).replace( "{count}" , job.result.folded ) );
    if ( job.result && job.result.nowhere ) notes.push( I18n.get( "local.nowhere" ).replace( "{count}" , job.result.nowhere ) );
    Dom.text( row.note , notes.join( " " ) );
    Dom.show( row.note , notes.length > 0 );
    // New sections are added below the ones already shown, never redrawn.
    for ( ; row.shown < job.outputs.length ; row.shown++ ) {
      const output = job.outputs[ row.shown ];
      const pages = output.meta.first_page === output.meta.last_page
        ? String( output.meta.first_page )
        : output.meta.first_page + "–" + output.meta.last_page;
      row.list.appendChild( Dom.el( "li" , { class: "d-flex flex-wrap align-items-baseline gap-2 py-1 border-bottom" , children: [
        Dom.el( "i" , { class: "bi bi-file-earmark-pdf text-body-secondary" , attrs: { "aria-hidden": "true" } } ),
        Dom.el( "a" , { class: "text-break flex-grow-1" , text: output.name , attrs: { href: output.url , download: output.name } } ),
        Dom.el( "span" , { class: "text-body-secondary text-nowrap" , text: pages + " · " + Files.size( output.size ) } ),
      ] } ) );
    }
    Dom.text( row.summary , I18n.get( "local.show_sections" ) );
    Dom.show( row.details , job.outputs.length > 0 );
  },

  paintBatch() {
    const finished = this.jobs.filter( ( job ) => [ "done" , "failed" , "cancelled" ].includes( job.state ) ).length;
    Dom.text( Dom.get( "local-summary" ) , I18n.get( this.running ? "local.summary_running" : "local.summary_finished" )
      .replace( "{done}" , this.running ? finished : this.jobs.filter( ( job ) => job.state === "done" ).length )
      .replace( "{count}" , this.jobs.length ) );
    const made = this.outputs().length > 0;
    Dom.show( Dom.get( "local-cancel" ) , this.running );
    Dom.show( Dom.get( "local-download-all" ) , made && !this.running );
    Dom.show( Dom.get( "local-save-folder" ) , made && !this.running && typeof window.showDirectoryPicker === "function" );
  },
};
