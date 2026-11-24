// Split by bookmarks level: the tool screen that splits PDFs in the browser, with
// qpdf compiled to WebAssembly (js/local/worker.js runs it; the split itself is
// js/local/split_bookmarks.js, the same split as the server's). The PDFs are
// never uploaded: the sections are saved straight from this page.
//
// Where splits run is the account's choice (Tools.mode, set on Account >
// Where your tools run; see js/tool_modes.js):
// - Automatic: this device if it looks up to it (WebAssembly and workers, at
//   least 4 cores, and at least 4 GB where the browser says), else the server;
// - This device: always here, if the browser can at all;
// - The server: PDFs picked here are uploaded (js/library.js does the
//   sending), split there as runs, and followed here as they go. What happens
//   to each upload afterwards is chosen under the drop zone (File.keep):
//   gone once its split is done, kept a day, or kept as retention says.
//
// When a batch ends, one file in all is downloaded at once; several are listed
// with "Download all" as one zip (js/zip.js here, GET /api/runs/download for
// the server). A cancelled or failed PDF can be started again from its row.
//
// Results made here land in the origin's private disk (OPFS) under a folder
// per batch, so a run of large sections never sits in memory. Folders older
// than a day are cleared when the page loads.
const Local = {
  tool: "split_bookmarks",
  // Where the choice lived before it moved to the account; cleared on load.
  oldPrefKey: "pdftools-engine.split_bookmarks",
  keepKey: "pdftools-keep-upload",
  // Uploads at once, as the import queue sends them.
  uploadWorkers: 2,
  // How long to wait for a stream event before reading again anyway.
  pollMs: 3000,
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
  // Where the batch on screen ran ("device" or "server"), and the options it
  // was split with, which a restart reuses.
  where: "device",
  options: null,

  init( me ) {
    try { window.localStorage.removeItem( this.oldPrefKey ); } catch ( error ) { /* private mode */ }
    if ( me.files_enabled === false ) return;
    const card = Dom.get( "local-card" );
    Dom.show( card , true );
    Dom.show( Dom.get( "tool-split-bookmarks" ) , true );
    [ [ "local-pick-button" , "local-pick" ] , [ "local-pick-folder-button" , "local-pick-folder" ] ].forEach( ( pair ) => {
      const input = Dom.get( pair[ 1 ] );
      Dom.get( pair[ 0 ] ).addEventListener( "click" , () => input.click() );
      input.addEventListener( "change" , () => {
        const chosen = Array.from( input.files ).map( ( file ) => {
          const path = file.webkitRelativePath || "";
          return { file: file , folder: path.includes( "/" ) ? path.slice( 0 , path.lastIndexOf( "/" ) ) : "" };
        } );
        input.value = "";
        this.picked( chosen );
      } );
    } );
    Dom.onPress( Dom.get( "local-cancel" ) , () => this.cancel() );
    Dom.onPress( Dom.get( "local-download-all" ) , () => this.downloadAll() );
    const keep = Dom.get( "local-keep" );
    keep.value = this.keepChoice();
    keep.addEventListener( "change" , () => {
      try { window.localStorage.setItem( this.keepKey , keep.value ); } catch ( error ) { /* private mode */ }
    } );
    // Re-check where splits run when the account's choice changes.
    window.addEventListener( "nav" , () => this.paintEngine() );
    Dom.onPress( Dom.get( "local-save-folder" ) , () => this.saveToFolder() );
    this.watchDrops( Dom.get( "tool-split-bookmarks" ) );
    window.addEventListener( "beforeunload" , ( event ) => {
      if ( this.running ) event.preventDefault();
    } );
    if ( typeof Fresh !== "undefined" && Fresh.holdWhile ) Fresh.holdWhile( () => this.running );
    this.paintEngine();
    this.sweep();
  },

  // ---- where it runs ---------------------------------------------------------

  preference() {
    return Tools.mode( this.tool );
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

  // Where it runs is not shown here (it is set on Account); only whether a
  // batch is under way, which holds the pickers, and, for the server, what
  // happens to the uploads.
  paintEngine() {
    Dom.get( "local-pick-button" ).disabled = this.running;
    Dom.get( "local-pick-folder-button" ).disabled = this.running;
    Dom.show( Dom.get( "local-keep-row" ) , this.engine() === "server" );
    Dom.get( "local-keep" ).disabled = this.running;
  },

  // "run" (the default), "day", or "" for the retention policy.
  keepChoice() {
    let saved = null;
    try { saved = window.localStorage.getItem( this.keepKey ); } catch ( error ) { /* private mode */ }
    return [ "run" , "day" , "" ].includes( saved ) ? saved : "run";
  },

  // ---- choosing ----------------------------------------------------------------

  // The whole tool screen takes a drop, of files or folders, as My files
  // does (Library.walk reads the folders; their entries have to be taken
  // during the drop event itself, before anything is awaited).
  watchDrops( panel ) {
    const carriesFiles = ( event ) => Array.from( event.dataTransfer.types ).includes( "Files" );
    const mark = ( on ) => Dom.get( "local-drop-zone" ).classList.toggle( "file-drop-active" , on );
    [ "dragenter" , "dragover" ].forEach( ( name ) => panel.addEventListener( name , ( event ) => {
      if ( !carriesFiles( event ) ) return;
      event.preventDefault();
      mark( true );
    } ) );
    panel.addEventListener( "dragleave" , ( event ) => {
      if ( !panel.contains( event.relatedTarget ) ) mark( false );
    } );
    panel.addEventListener( "drop" , async ( event ) => {
      if ( !carriesFiles( event ) ) return;
      event.preventDefault();
      mark( false );
      const entries = Array.from( event.dataTransfer.items || [] )
        .map( ( item ) => item.webkitGetAsEntry ? item.webkitGetAsEntry() : null )
        .filter( Boolean );
      const plain = Array.from( event.dataTransfer.files ).map( ( file ) => ( { file: file , folder: "" } ) );
      try {
        this.picked( entries.length ? await Library.walk( entries ) : plain );
      } catch ( error ) {
        App.showError( error.message );
      }
    } );
  },

  // chosen: { file , folder } from a picker or a drop: split here, or
  // uploaded and split on the server.
  picked( chosen ) {
    const pdfs = chosen.filter( ( item ) => Library.isPdf( item.file ) );
    const skipped = chosen.length - pdfs.length;
    if ( skipped > 0 ) Dom.toast( I18n.get( "library.skipped" ).replace( "{count}" , skipped ) , "error" );
    if ( pdfs.length === 0 || this.running ) return;
    if ( this.engine() === "server" ) this.startServer( pdfs );
    else this.start( pdfs.map( ( item ) => item.file ) );
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
    if ( this.where === "server" ) {
      this.jobs.forEach( ( job ) => {
        job.cancelled = true;
        if ( job.runId && [ "queued" , "splitting" ].includes( job.state ) ) Api.cancelRun( job.runId ).catch( () => {} );
      } );
      this.wake();
      return;
    }
    this.dropWorker();
    if ( this.pending ) this.pending.reject( new Error( "cancelled" ) );
  },

  // ---- a batch ---------------------------------------------------------------

  // A new batch on screen, run where.
  begin( where , jobs ) {
    this.urls.forEach( ( url ) => URL.revokeObjectURL( url ) );
    this.urls = [];
    this.cancelled = false;
    this.where = where;
    this.options = null;
    this.jobs = jobs;
    Dom.swap( Dom.get( "local-list" ) , ...this.jobs.map( ( job ) => this.jobRow( job ) ) );
    Dom.show( Dom.get( "local-batch" ) , true );
  },

  // Runs work (a batch, or a restart) with the pickers held, then offers
  // what it made.
  async busy( work ) {
    this.running = true;
    this.cancelled = false;
    this.paintEngine();
    this.paintBatch();
    try {
      await work();
    } catch ( error ) {
      App.showError( error.message );
    } finally {
      this.running = false;
      this.pending = null;
      this.paintEngine();
      this.paintBatch();
      this.jobs.forEach( ( job ) => this.paintJob( job ) );
    }
    this.offer();
  },

  async start( files ) {
    this.begin( "device" , files.map( ( file ) => ( { file , state: "reading" , outputs: [] , fraction: 0 , name: "" } ) ) );
    this.batchId = Date.now() + "-" + Math.random().toString( 36 ).slice( 2 , 8 );
    await this.busy( async () => {
      await this.inspectAll();
      const ready = this.jobs.filter( ( job ) => job.state === "waiting" );
      const options = ready.length && !this.cancelled ? await this.askOptions( ready ) : null;
      this.options = options;
      if ( !options ) {
        ready.forEach( ( job ) => this.setState( job , "cancelled" ) );
      } else {
        for ( const job of ready ) {
          if ( this.cancelled ) this.setState( job , "cancelled" );
          else await this.splitOne( job , options );
        }
      }
    } );
  },

  // ---- a batch on the server ---------------------------------------------------

  async startServer( pdfs ) {
    const keep = Dom.get( "local-keep" ).value;
    this.begin( "server" , pdfs.map( ( item ) => ( {
      file: item.file , folder: item.folder , keep: keep , tool: true , sent: 0 ,
      state: "sending" , outputs: [] , fraction: 0 , name: "",
      onPaint: ( job ) => this.uploadPainted( job ),
    } ) ) );
    await this.busy( async () => {
      await this.uploadAll();
      await Promise.all( this.jobs.filter( ( job ) => job.state === "reading" ).map( ( job ) => this.waitRead( job ) ) );
      const ready = this.jobs.filter( ( job ) => job.state === "waiting" );
      const options = ready.length && !this.cancelled ? await this.askOptions( ready ) : null;
      this.options = options;
      if ( !options ) {
        ready.forEach( ( job ) => this.setState( job , "cancelled" ) );
        return;
      }
      const started = await Api.startActionMany( ready.map( ( job ) => job.id ) , this.tool , options );
      ready.forEach( ( job ) => {
        const run = started.runs.find( ( one ) => one.file_id === job.id );
        const refused = started.skipped.find( ( one ) => one.file_id === job.id );
        if ( run ) {
          job.runId = run.id;
          this.setState( job , "queued" );
        } else {
          this.setState( job , "failed" , refused ? refused.error : "failed" );
        }
      } );
      await this.follow();
    } );
  },

  // Library.upload calls this for each step of an upload it sends for us;
  // while it does, the job's state is its: "checking" (is it on the server
  // already?) or "sending".
  uploadPainted( job ) {
    const reached = job.state === "checking" ? ( job.checked || 0 ) : job.sent;
    job.fraction = job.file.size ? reached / job.file.size : 1;
    this.paintJob( job );
  },

  async uploadAll() {
    const next = () => this.jobs.find( ( job ) => job.state === "sending" && !job.taken );
    const worker = async () => {
      for ( let job = next() ; job && !this.cancelled ; job = next() ) {
        job.taken = true;
        try {
          await Library.upload( job );
          this.setState( job , "reading" );
        } catch ( error ) {
          this.setState( job , this.cancelled ? "cancelled" : "failed" , this.cancelled ? "" : "upload" );
        }
      }
    };
    await Promise.all( Array.from( { length: this.uploadWorkers } , worker ) );
    this.jobs.filter( ( job ) => !job.taken ).forEach( ( job ) => this.setState( job , "cancelled" ) );
    Library.refreshSoon();
  },

  // Until the server has had its first look at an upload: is it a PDF, how
  // deep do its bookmarks go.
  async waitRead( job ) {
    while ( !this.cancelled ) {
      let found;
      try {
        found = await Api.file( job.id );
      } catch ( error ) {
        this.setState( job , "failed" , "upload" );
        return;
      }
      if ( found.pdf_state === "invalid" ) {
        this.setState( job , "failed" , found.pdf_error || "damaged" );
        return;
      }
      if ( found.pdf_state === "ok" ) {
        job.info = { levels: found.levels , bookmarks: found.bookmarks , pages: found.pages };
        this.setState( job , found.bookmarks > 0 ? "waiting" : "failed" , found.bookmarks > 0 ? "" : "no_bookmarks" );
        return;
      }
      await this.nap( "work:files" );
    }
    this.setState( job , "cancelled" );
  },

  // The server's runs for this batch, read again each time the stream says a
  // run moved (or every pollMs), until none is still going.
  async follow() {
    const going = () => this.jobs.filter( ( job ) => job.runId && [ "queued" , "splitting" ].includes( job.state ) );
    while ( going().length > 0 ) {
      for ( const job of going() ) {
        let detail;
        try {
          detail = await Api.run( job.runId );
        } catch ( error ) {
          this.setState( job , "failed" , "failed" );
          continue;
        }
        job.fraction = detail.progress;
        job.name = detail.step;
        job.result = detail.result;
        if ( detail.state === "done" ) {
          job.outputs = detail.files.map( ( file ) => ( {
            name: file.name , size: file.size , pages: file.pages , id: file.id , url: Api.fileDownloadPath( file.id ),
          } ) );
          this.setState( job , "done" );
        } else if ( detail.state === "failed" ) {
          this.setState( job , "failed" , detail.message );
        } else if ( detail.state === "cancelled" ) {
          this.setState( job , "cancelled" );
        } else {
          this.setState( job , detail.state === "running" ? "splitting" : "queued" );
        }
      }
      if ( going().length > 0 ) await this.nap( "work:runs" );
    }
  },

  // Until the stream says name happened, pollMs passes, or Stop is pressed.
  nap( name ) {
    return new Promise( ( resolve ) => {
      const done = () => {
        window.removeEventListener( name , done );
        window.clearTimeout( timer );
        this.waking = null;
        resolve();
      };
      const timer = window.setTimeout( done , this.pollMs );
      window.addEventListener( name , done );
      this.waking = done;
    } );
  },

  wake() {
    if ( this.waking ) this.waking();
  },

  // ---- again ----------------------------------------------------------------

  restartable( job ) {
    if ( this.running || ![ "cancelled" , "failed" ].includes( job.state ) ) return false;
    if ( this.where === "server" ) return Boolean( job.runId );
    return Boolean( this.options && job.info && job.info.bookmarks > 0 );
  },

  async restart( job ) {
    if ( !this.restartable( job ) ) return;
    job.outputs = [];
    job.fraction = 0;
    job.result = null;
    if ( job.row ) {
      Dom.swap( job.row.list );
      job.row.shown = 0;
    }
    await this.busy( async () => {
      if ( this.where === "server" ) {
        await Api.restartRun( job.runId );
        this.setState( job , "queued" );
        await this.follow();
      } else {
        await this.splitOne( job , this.options );
      }
    } );
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
      // Each section is read back from disk as it comes; the split can say
      // it is done before the last read has finished.
      const adding = [];
      job.result = await this.call( { type: "split" , file: job.file , options: options , store: this.store , batch: this.batchId , job: "file-" + index } , ( data ) => adding.push( ( async () => {
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
      } )() ) );
      await Promise.all( adding );
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

  save( url , name ) {
    const link = Dom.el( "a" , { attrs: { href: url , download: name || "" } } );
    document.body.appendChild( link );
    link.click();
    link.remove();
  },

  // Once a batch (or a restart) ends: one file in all is downloaded at once,
  // with a toast to fetch it again in case the browser held it back; several
  // are listed, open, with "Download all" waiting.
  offer() {
    const outputs = this.outputs();
    if ( this.cancelled || outputs.length === 0 ) return;
    if ( outputs.length === 1 ) {
      const only = outputs[ 0 ];
      this.save( only.url , only.name );
      Dom.toast( I18n.get( "local.downloading" ).replace( "{name}" , only.name ) , "ok" , {
        text: I18n.get( "local.download_again" ),
        run: () => this.save( only.url , only.name ),
      } );
      return;
    }
    this.jobs.forEach( ( job ) => {
      if ( job.row && job.outputs.length ) job.row.details.open = true;
    } );
    Dom.toast( I18n.get( "local.ready" ).replace( "{count}" , outputs.length ) , "ok" , {
      text: I18n.get( "local.download_all" ),
      run: () => this.downloadAll(),
    } );
    Dom.get( "local-download-all" ).focus( { preventScroll: false } );
  },

  // Everything as one zip: the server makes it for its runs; here it is
  // built from the sections on disk. Past what a plain zip holds, one
  // download each, and the browser may ask once whether this page may save
  // several files.
  async downloadAll() {
    const outputs = this.outputs();
    if ( this.where === "server" ) {
      this.save( Api.runsDownloadPath( this.jobs.filter( ( job ) => job.outputs.length ).map( ( job ) => job.runId ) ) );
      return;
    }
    const several = this.jobs.filter( ( job ) => job.outputs.length ).length > 1;
    const entries = outputs.map( ( output ) => ( {
      name: several ? output.job.file.name.replace( /\.pdf$/i , "" ) + "/" + output.name : output.name,
      file: output.file,
    } ) );
    if ( Zip.fits( entries ) ) {
      const button = Dom.get( "local-download-all" );
      button.disabled = true;
      try {
        const zip = await Zip.build( entries );
        const url = URL.createObjectURL( zip );
        this.urls.push( url );
        const name = several
          ? I18n.get( "local.zip_many" ).replace( "{count}" , outputs.length )
          : I18n.get( "local.zip_one" ).replace( "{name}" , this.jobs.find( ( job ) => job.outputs.length ).file.name.replace( /\.pdf$/i , "" ) );
        this.save( url , name );
      } catch ( error ) {
        App.showError( error.message );
      } finally {
        button.disabled = false;
      }
      return;
    }
    for ( const output of outputs ) {
      this.save( output.url , output.name );
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
    const again = Dom.el( "button" , {
      class: "btn btn-sm btn-outline-primary py-0",
      attrs: { type: "button" },
      children: [
        Dom.el( "i" , { class: "bi bi-arrow-clockwise me-1" , attrs: { "aria-hidden": "true" } } ),
        Dom.el( "span" , { text: I18n.get( "local.restart" ) } ),
      ],
      on: { click: () => this.restart( job ) },
    } );
    const bar = Dom.el( "progress" , { class: "w-100" , attrs: { max: "1" , value: "0" , "aria-label": job.file.name } } );
    const note = Dom.el( "div" , { class: "text-body-secondary" } );
    const list = Dom.el( "ul" , { class: "list-unstyled mb-0 mt-1" } );
    const summary = Dom.el( "summary" , { class: "text-body-secondary" } );
    const details = Dom.el( "details" , { class: "mt-1" , children: [ summary , list ] } );
    const element = Dom.el( "li" , { class: "list-group-item px-0" , children: [
      Dom.el( "div" , { class: "d-flex flex-wrap align-items-center gap-2" , children: [ name , status , again ] } ),
      bar, note, details,
    ] } );
    job.row = { element , status , bar , note , list , summary , details , again , shown: 0 };
    this.paintJob( job );
    return element;
  },

  paintJob( job ) {
    const row = job.row;
    if ( !row ) return;
    const size = job.outputs.reduce( ( sum , output ) => sum + output.size , 0 );
    const percent = Math.floor( job.fraction * 100 );
    const words = {
      checking: I18n.get( "local.checking" ).replace( "{percent}" , percent ),
      sending: I18n.get( "local.uploading" ).replace( "{percent}" , percent ),
      queued: I18n.get( "local.queued" ),
      reading: I18n.get( "local.reading" ),
      waiting: I18n.get( "local.waiting" ),
      splitting: I18n.get( "local.splitting" ).replace( "{percent}" , percent ).replace( "{name}" , job.name || job.file.name ),
      done: I18n.get( "local.done" ).replace( "{count}" , job.outputs.length ).replace( "{size}" , Files.size( size ) ),
      failed: I18n.get( "local.failed" ).replace( "{reason}" , I18n.get( "local.errors." + job.reason ) || job.reason ),
      cancelled: I18n.get( "local.cancelled" ),
    };
    Dom.text( row.status , words[ job.state ] );
    row.status.className = "text-nowrap " + ( job.state === "failed" ? "text-danger" : job.state === "done" ? "text-success" : "text-body-secondary" );
    row.bar.value = job.state === "done" ? 1 : job.fraction;
    Dom.show( row.bar , [ "splitting" , "checking" , "sending" ].includes( job.state ) );
    Dom.show( row.again , this.restartable( job ) );
    const notes = [];
    if ( job.result && job.result.folded ) notes.push( I18n.get( "local.folded" ).replace( "{count}" , job.result.folded ) );
    if ( job.result && job.result.nowhere ) notes.push( I18n.get( "local.nowhere" ).replace( "{count}" , job.result.nowhere ) );
    Dom.text( row.note , notes.join( " " ) );
    Dom.show( row.note , notes.length > 0 );
    // New sections are added below the ones already shown, never redrawn.
    for ( ; row.shown < job.outputs.length ; row.shown++ ) {
      const output = job.outputs[ row.shown ];
      const pages = !output.meta
        ? I18n.get( "runs.section_pages" ).replace( "{count}" , output.pages )
        : output.meta.first_page === output.meta.last_page
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
    Dom.show( Dom.get( "local-save-folder" ) , made && !this.running && this.where === "device" && typeof window.showDirectoryPicker === "function" );
  },
};
