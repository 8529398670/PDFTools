// The Library screen: drop PDFs, or whole folders of them, and they are
// imported at once; then send any of them to an action.
//
// Importing is built for books of several GB:
// - a file goes up in pieces (the server says how big), several at once, and
//   two files at once. Nothing is read into memory beyond the pieces in flight:
//   each is a Blob.slice of the file on disk.
// - the server keeps which pieces have arrived. An upload cut off (a closed
//   tab, a lost connection) is remembered here by name, size and date, and
//   dropping the same file again sends only what is missing.
// - once the last piece is in, the server takes a first look (pages,
//   bookmarks), and says so on the work stream (runs.js), which refreshes the
//   table.
const Library = {
  me: null,
  everyone: false,
  // File ids ticked in the table, kept across refreshes.
  selected: new Set(),
  // What the table last showed, by id, for the split dialog.
  shown: new Map(),
  // Pieces in flight per file, and files at once.
  pieceWorkers: 4,
  fileWorkers: 2,
  attempts: 6,
  retryWait: 1500,
  // Upload state: the queue of { file , folder , row , ... } and its totals.
  queue: [],
  cancelled: false,
  uploading: false,
  resumeKey: "pdftools-uploads",

  async init( me ) {
    this.me = me;
    if ( me.files_enabled === false ) return;
    Dom.show( Dom.get( "library-panel" ) , true );
    Dom.show( Dom.get( "runs-panel" ) , true );

    const files = Dom.get( "pick-files" );
    const folder = Dom.get( "pick-folder" );
    Dom.get( "pick-files-button" ).addEventListener( "click" , () => files.click() );
    Dom.get( "pick-folder-button" ).addEventListener( "click" , () => folder.click() );
    files.addEventListener( "change" , () => this.picked( files ) );
    folder.addEventListener( "change" , () => this.picked( folder ) );
    Dom.get( "import-cancel" ).addEventListener( "click" , () => { this.cancelled = true; } );
    this.watchDrops( Dom.get( "library-panel" ) );

    Pager.sortable( "files-table" , () => this.refresh() );
    Pager.search( "files-table" , "files-search" , () => this.refresh() );
    Dom.get( "files-select-all" ).addEventListener( "change" , ( event ) => this.selectAll( event.target.checked ) );
    Dom.onPress( Dom.get( "split-selected" ) , () => this.split( this.chosen() ) );
    window.addEventListener( "beforeunload" , ( event ) => {
      if ( this.uploading ) event.preventDefault();
    } );
    Fresh.holdWhile( () => this.uploading );
    window.addEventListener( "work:files" , () => this.refreshSoon() );
    window.addEventListener( "nav" , ( event ) => {
      if ( event.detail.screen === "library" && this.stale ) this.refreshSoon();
    } );
    if ( me.role === "admin" ) {
      Dom.show( Dom.get( "files-everyone-field" ) , true );
      Dom.get( "files-everyone" ).addEventListener( "change" , this.onEveryone.bind( this ) );
    }
    await this.refresh();
  },

  async onEveryone( event ) {
    this.everyone = event.target.checked;
    Dom.show( Dom.get( "files-owner-column" ) , this.everyone );
    this.selected.clear();
    if ( Pager.sortOf( "files-table" ).sort === "user_name" ) Pager.clearSort( "files-table" );
    await this.refresh();
  },

  // ---- choosing what to import --------------------------------------------

  isPdf( file ) {
    return /\.pdf$/i.test( file.name ) || file.type === "application/pdf";
  },

  picked( input ) {
    const chosen = Array.from( input.files ).map( ( file ) => {
      const path = file.webkitRelativePath || "";
      return { file: file , folder: path.includes( "/" ) ? path.slice( 0 , path.lastIndexOf( "/" ) ) : "" };
    } );
    input.value = "";
    this.enqueue( chosen );
  },

  // The whole screen takes a drop, of files or folders. Folders are walked
  // with the entries API; the entries have to be taken during the drop event
  // itself, before anything is awaited.
  watchDrops( panel ) {
    const carriesFiles = ( event ) => Array.from( event.dataTransfer.types ).includes( "Files" );
    const mark = ( on ) => Dom.get( "drop-zone" ).classList.toggle( "file-drop-active" , on );
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
        this.enqueue( entries.length ? await this.walk( entries ) : plain );
      } catch ( error ) {
        App.showError( error.message );
      }
    } );
  },

  async walk( entries ) {
    const found = [];
    const readAll = ( reader ) => new Promise( ( resolve , reject ) => reader.readEntries( resolve , reject ) );
    const visit = async ( entry , folder ) => {
      if ( entry.isFile ) {
        const file = await new Promise( ( resolve , reject ) => entry.file( resolve , reject ) );
        found.push( { file: file , folder: folder } );
        return;
      }
      if ( !entry.isDirectory ) return;
      const inside = folder ? folder + "/" + entry.name : entry.name;
      const reader = entry.createReader();
      // readEntries answers in batches until it answers none.
      for ( let batch = await readAll( reader ) ; batch.length ; batch = await readAll( reader ) ) {
        for ( const child of batch ) await visit( child , inside );
      }
    };
    for ( const entry of entries ) await visit( entry , "" );
    return found;
  },

  // ---- uploading -----------------------------------------------------------

  enqueue( chosen ) {
    const pdfs = chosen.filter( ( item ) => this.isPdf( item.file ) );
    const skipped = chosen.length - pdfs.length;
    if ( skipped > 0 ) Dom.toast( I18n.get( "library.skipped" ).replace( "{count}" , skipped ) , "error" );
    if ( pdfs.length === 0 ) return;
    if ( !this.uploading ) {
      this.queue = [];
      this.cancelled = false;
      Dom.swap( Dom.get( "import-list" ) );
    }
    pdfs.forEach( ( item ) => {
      item.sent = 0;
      item.state = "waiting";
      item.row = this.queueRow( item );
      Dom.get( "import-list" ).appendChild( item.row.element );
      this.queue.push( item );
    } );
    Dom.show( Dom.get( "import-queue" ) , true );
    this.paintTotals();
    if ( !this.uploading ) this.runQueue();
  },

  async runQueue() {
    this.uploading = true;
    this.started = Date.now();
    this.startedBytes = 0;
    const next = () => this.queue.find( ( item ) => item.state === "waiting" );
    const worker = async () => {
      for ( let item = next() ; item && !this.cancelled ; item = next() ) {
        item.state = "sending";
        this.paintItem( item );
        try {
          await this.upload( item );
          item.state = "done";
        } catch ( error ) {
          item.state = this.cancelled ? "cancelled" : "failed";
          item.reason = I18n.get( "errors." + error.message ) || error.message;
        }
        this.paintItem( item );
        this.paintTotals();
        this.refreshSoon();
      }
    };
    await Promise.all( Array.from( { length: this.fileWorkers } , worker ) );
    this.queue.filter( ( item ) => item.state === "waiting" ).forEach( ( item ) => {
      item.state = "cancelled";
      this.paintItem( item );
    } );
    this.uploading = false;
    this.paintTotals();
    const done = this.queue.filter( ( item ) => item.state === "done" ).length;
    const failed = this.queue.filter( ( item ) => item.state === "failed" ).length;
    if ( done > 0 ) Dom.toast( I18n.get( "library.imported" ).replace( "{count}" , done ) , "ok" );
    if ( failed > 0 ) App.showError( I18n.get( "library.failed" ).replace( "{count}" , failed ) );
    await this.refresh();
  },

  // Where an upload of this very file was cut off, if it was.
  remembered() {
    try {
      return JSON.parse( window.localStorage.getItem( this.resumeKey ) || "{}" );
    } catch ( error ) {
      return {};
    }
  },

  remember( item , id ) {
    const all = this.remembered();
    const key = [ item.folder , item.file.name , item.file.size , item.file.lastModified ].join( "|" );
    if ( id ) all[ key ] = id;
    else delete all[ key ];
    try { window.localStorage.setItem( this.resumeKey , JSON.stringify( all ) ); } catch ( error ) { /* private mode */ }
    return all[ key ];
  },

  async resumable( item ) {
    const key = [ item.folder , item.file.name , item.file.size , item.file.lastModified ].join( "|" );
    const id = this.remembered()[ key ];
    if ( !id ) return null;
    try {
      const found = await Api.file( id );
      if ( found.state === "uploading" && found.size === item.file.size ) return found;
    } catch ( error ) { /* gone: start again */ }
    this.remember( item , null );
    return null;
  },

  async upload( item ) {
    const file = item.file;
    let created = await this.resumable( item );
    if ( created ) {
      item.sent = ( created.chunks - created.missing.length ) * created.chunk_bytes;
    } else {
      created = await Api.createFile( file.name , file.size , file.type || "application/pdf" , item.folder );
      this.remember( item , created.id );
    }
    item.id = created.id;
    try {
      let missing = created.missing.slice();
      for ( let round = 0 ; ; round++ ) {
        await this.sendPieces( item , created , missing );
        try {
          await Api.finishFile( created.id );
          break;
        } catch ( error ) {
          // Pieces the server does not have after all: send those again, once.
          if ( error.status === 409 && error.payload && error.payload.missing && round === 0 ) {
            missing = error.payload.missing;
            continue;
          }
          throw error;
        }
      }
      this.remember( item , null );
    } catch ( error ) {
      // Cancelled: it would hold its share of the quota until the sweep. A
      // failure keeps its pieces, so dropping the file again resumes it.
      if ( this.cancelled ) {
        await Api.deleteFile( created.id ).catch( () => {} );
        this.remember( item , null );
      }
      throw error;
    }
  },

  async sendPieces( item , created , missing ) {
    const pending = missing.slice();
    const worker = async () => {
      while ( pending.length > 0 ) {
        if ( this.cancelled ) throw new Error( "cancelled" );
        const index = pending.shift();
        await this.sendPiece( created , item.file , index );
        const start = index * created.chunk_bytes;
        item.sent += Math.min( created.chunk_bytes , item.file.size - start );
        this.paintItem( item );
        this.paintTotals();
      }
    };
    await Promise.all( Array.from( { length: Math.min( this.pieceWorkers , Math.max( pending.length , 1 ) ) } , worker ) );
  },

  async sendPiece( created , file , index ) {
    const start = index * created.chunk_bytes;
    const piece = file.slice( start , start + created.chunk_bytes );
    for ( let attempt = 1 ; ; attempt++ ) {
      try {
        return await Api.sendFileChunk( created.id , index , piece );
      } catch ( error ) {
        if ( this.cancelled ) throw error;
        // No status is the network; 409 is the same piece already being
        // written by a retry of ours, which a moment later will be there.
        const passing = !error.status || error.status === 409 || error.status === 429 || error.status >= 500;
        if ( !passing || attempt >= this.attempts ) throw error;
        await new Promise( ( resolve ) => setTimeout( resolve , this.retryWait * attempt ) );
      }
    }
  },

  // ---- showing the upload --------------------------------------------------

  queueRow( item ) {
    const name = Dom.el( "span" , { class: "text-break flex-grow-1" , text: item.folder ? item.folder + "/" + item.file.name : item.file.name } );
    const status = Dom.el( "span" , { class: "text-body-secondary text-nowrap" } );
    const bar = Dom.el( "progress" , { class: "w-100" , attrs: { max: String( Math.max( item.file.size , 1 ) ) , value: "0" } } );
    const element = Dom.el( "li" , { class: "list-group-item px-0" , children: [
      Dom.el( "div" , { class: "d-flex flex-wrap gap-2" , children: [ name , status ] } ),
      bar,
    ] } );
    bar.setAttribute( "aria-label" , item.file.name );
    return { element , status , bar };
  },

  paintItem( item ) {
    item.row.bar.value = item.state === "done" ? item.file.size : item.sent;
    Dom.show( item.row.bar , item.state === "sending" );
    const percent = item.file.size ? Math.floor( item.sent * 100 / item.file.size ) : 100;
    const words = {
      waiting: I18n.get( "library.state_waiting" ),
      sending: I18n.get( "library.state_sending" ).replace( "{percent}" , percent ).replace( "{size}" , Files.size( item.file.size ) ),
      done: I18n.get( "library.state_done" ),
      failed: I18n.get( "library.state_failed" ).replace( "{reason}" , item.reason || "" ),
      cancelled: I18n.get( "library.state_cancelled" ),
    };
    Dom.text( item.row.status , words[ item.state ] );
    item.row.status.className = "text-nowrap " + ( item.state === "failed" ? "text-danger" : "text-body-secondary" );
  },

  paintTotals() {
    const total = this.queue.reduce( ( sum , item ) => sum + item.file.size , 0 );
    const sent = this.queue.reduce( ( sum , item ) => sum + ( item.state === "done" ? item.file.size : item.sent ) , 0 );
    const done = this.queue.filter( ( item ) => item.state === "done" ).length;
    const bar = Dom.get( "import-progress" );
    bar.max = Math.max( total , 1 );
    bar.value = sent;
    const seconds = Math.max( ( Date.now() - ( this.started || Date.now() ) ) / 1000 , 0.001 );
    const speed = this.uploading ? I18n.get( "library.speed" ).replace( "{rate}" , Files.size( sent / seconds ) ) : "";
    Dom.text( Dom.get( "import-summary" ) , I18n.get( this.uploading ? "library.summary_running" : "library.summary_finished" )
      .replace( "{done}" , done )
      .replace( "{count}" , this.queue.length )
      .replace( "{sent}" , Files.size( sent ) )
      .replace( "{total}" , Files.size( total ) )
      .replace( "{speed}" , speed ) );
    Dom.show( Dom.get( "import-cancel" ) , this.uploading );
  },

  // ---- the table -----------------------------------------------------------

  // Not while another screen shows: that is read on coming back. While a
  // folder is importing, files land every moment; a read every few seconds
  // keeps the page within the general rate limit (120 a minute).
  refreshSoon() {
    if ( !Dom.get( "library-panel" ).classList.contains( "view-active" ) ) {
      this.stale = true;
      return;
    }
    this.stale = false;
    if ( this.refreshTimer ) return;
    this.refreshTimer = window.setTimeout( () => {
      this.refreshTimer = null;
      this.refresh();
    } , this.uploading ? 4000 : 1000 );
  },

  async refreshUsage() {
    try {
      const usage = await Api.storage();
      const bar = Dom.get( "files-usage-bar" );
      bar.max = Math.max( usage.quota_bytes , 1 );
      bar.value = usage.used_bytes;
      Dom.text( Dom.get( "files-usage-text" ) , I18n.get( "files.usage" )
        .replace( "{used}" , Files.size( usage.used_bytes ) )
        .replace( "{quota}" , Files.size( usage.quota_bytes ) ) );
      Dom.show( Dom.get( "files-usage" ) , true );
      if ( this.me.role !== "admin" ) return;
      const all = await Api.allStorage();
      const line = all.disk_free_bytes === undefined ? I18n.get( "files.usage_all" ) : I18n.get( "files.usage_all_disk" );
      Dom.text( Dom.get( "files-usage-all" ) , line
        .replace( "{used}" , Files.size( all.used_bytes ) )
        .replace( "{free}" , Files.size( all.disk_free_bytes || 0 ) ) );
    } catch ( error ) { /* the list works without this */ }
    Dom.show( Dom.get( "files-usage-all" ) , this.everyone );
  },

  async refresh() {
    const params = Pager.params( "files-table" );
    const fetchPage = ( offset ) => this.everyone ? Api.allFiles( offset , params ) : Api.files( offset , params );
    this.shown = new Map();
    const page = await Pager.load( "files-table" , "files" , fetchPage , this.renderRow.bind( this ) );
    if ( page ) {
      // A ticked file that is no longer listed is no longer ticked.
      [ ...this.selected ].forEach( ( id ) => { if ( !this.shown.has( id ) ) this.selected.delete( id ); } );
      this.paintSelection();
    }
    await this.refreshUsage();
  },

  splittable( file ) {
    return file.pdf_state === "ok" && file.bookmarks > 0;
  },

  pagesCell( file ) {
    if ( file.pdf_state === "pending" ) {
      return [ Dom.el( "span" , { class: "spinner-border spinner-border-sm me-1" , attrs: { "aria-hidden": "true" } } ) ,
        Dom.el( "span" , { class: "text-body-secondary" , text: I18n.get( "library.reading" ) } ) ];
    }
    if ( file.pdf_state === "invalid" ) {
      return [ Dom.badge( I18n.get( "library.invalid_" + file.pdf_error ) || I18n.get( "library.invalid_damaged" ) , "danger" ) ];
    }
    return [ Dom.el( "span" , { text: String( file.pages ) } ) ];
  },

  bookmarksCell( file ) {
    if ( file.pdf_state !== "ok" ) return [];
    if ( file.bookmarks === 0 ) return [ Dom.el( "span" , { class: "text-body-secondary" , text: I18n.get( "library.no_bookmarks" ) } ) ];
    return [ Dom.el( "span" , { text: I18n.get( "library.bookmarks_count" )
      .replace( "{count}" , file.bookmarks )
      .replace( "{levels}" , file.levels.length ) } ) ];
  },

  renderRow( file ) {
    this.shown.set( file.id , file );
    const path = this.everyone ? Api.anyFileDownloadPath( file.id ) : Api.fileDownloadPath( file.id );
    const download = Dom.el( "a" , {
      class: "btn btn-sm btn-outline-secondary",
      text: I18n.get( "files.download_button" ),
      attrs: { href: path , download: file.name },
    } );
    const split = !this.everyone ? Dom.el( "button" , {
      class: "btn btn-sm btn-outline-primary",
      text: I18n.get( "library.split_button" ),
      on: { click: () => this.split( [ file ] ) },
    } ) : null;
    if ( split && !this.splittable( file ) ) split.disabled = true;

    const tick = Dom.el( "input" , { class: "form-check-input" , attrs: { type: "checkbox" , "aria-label": file.name } } );
    tick.checked = this.selected.has( file.id );
    tick.disabled = this.everyone;
    tick.addEventListener( "change" , () => {
      if ( tick.checked ) this.selected.add( file.id );
      else this.selected.delete( file.id );
      this.paintSelection();
    } );

    const details = [ this.nameCell( file , download ) ];
    if ( file.folder ) details.push( Dom.el( "div" , { class: "small text-body-secondary text-break" , children: [
      Dom.el( "i" , { class: "bi bi-folder2 me-1" , attrs: { "aria-hidden": "true" } } ),
      Dom.el( "span" , { text: file.folder } ),
    ] } ) );
    if ( file.title && file.title !== file.name ) details.push( Dom.el( "div" , { class: "small text-body-secondary text-break" , text: file.title } ) );

    const cells = [
      Dom.el( "td" , { class: "table-check" , attrs: { "data-write": "" } , children: [ tick ] } ),
      Dom.el( "td" , { class: "text-break cell-name" , children: details } ),
      Dom.el( "td" , { class: "text-nowrap" , children: this.pagesCell( file ) } ),
      Dom.el( "td" , { class: "text-nowrap" , children: this.bookmarksCell( file ) } ),
      Dom.el( "td" , { class: "text-nowrap" , text: Files.size( file.size ) } ),
      Dom.el( "td" , { class: "text-nowrap" , children: [ Dom.when( file.created_at ) ] } ),
      Dom.el( "td" , { class: "text-nowrap" , children: [ file.expires_at ? Dom.when( file.expires_at ) : Dom.el( "span" , { class: "text-body-secondary" , text: I18n.get( "library.kept" ) } ) ] } ),
      Dom.el( "td" , { class: "text-nowrap" , children: [ Dom.rowActions( file.name , [
        split,
        download,
        Dom.el( "button" , {
          class: "btn btn-sm btn-outline-danger",
          text: I18n.get( "files.delete_button" ),
          on: { click: () => this.remove( file ) },
        } ),
      ] , 1 ) ] } ),
    ];
    if ( this.everyone ) cells.splice( 2 , 0 , Dom.el( "td" , { text: file.user_name || ( "#" + file.user_id ) } ) );
    Dom.get( "files-table" ).querySelector( "tbody" ).appendChild( Dom.el( "tr" , { children: cells } ) );
  },

  nameCell( file , link ) {
    const mine = !this.everyone;
    const rename = ( name , expect ) => mine ? Api.renameFile( file.id , name , expect ) : Api.renameAnyFile( file.id , name , expect );
    return Dom.editable( file.name , {
      label: I18n.get( "files.table_name" ),
      maxLength: 255,
      save: async ( value ) => {
        const previous = file.name;
        const renamed = await rename( value , previous );
        if ( renamed.name === previous ) return previous;
        file.name = renamed.name;
        link.download = renamed.name;
        Undo.record( {
          label: I18n.get( "undo.rename_file" ),
          toast: true,
          undo: async () => { await rename( previous , renamed.name ); await this.refresh(); },
          redo: async () => { await rename( renamed.name , previous ); await this.refresh(); },
        } );
        return renamed.name;
      },
    } );
  },

  async remove( file ) {
    const mine = !this.everyone;
    const remove = () => mine ? Api.deleteFile( file.id ) : Api.deleteAnyFile( file.id );
    const restore = () => mine ? Api.restoreFile( file.id ) : Api.restoreAnyFile( file.id );
    try {
      await remove();
      this.selected.delete( file.id );
      await this.refresh();
    } catch ( error ) {
      App.showError( error.message );
      return;
    }
    Undo.record( {
      label: I18n.get( "undo.deleted_file" ),
      toast: true,
      undo: async () => { await restore(); await this.refresh(); },
      redo: async () => { await remove(); await this.refresh(); },
    } );
  },

  // ---- choosing and splitting ---------------------------------------------

  chosen() {
    return [ ...this.selected ].map( ( id ) => this.shown.get( id ) ).filter( Boolean );
  },

  selectAll( on ) {
    this.shown.forEach( ( file , id ) => {
      if ( on ) this.selected.add( id );
      else this.selected.delete( id );
    } );
    Dom.all( "#files-table tbody input[type=checkbox]" ).forEach( ( box ) => { box.checked = on; } );
    this.paintSelection();
  },

  paintSelection() {
    const chosen = this.chosen();
    const ready = chosen.filter( ( file ) => this.splittable( file ) );
    const button = Dom.get( "split-selected" );
    button.disabled = ready.length === 0;
    Dom.text( Dom.get( "split-selected-text" ) , ready.length > 0
      ? I18n.get( "library.split_selected_count" ).replace( "{count}" , ready.length )
      : I18n.get( "library.split_selected" ) );
    const all = Dom.get( "files-select-all" );
    all.checked = this.shown.size > 0 && chosen.length === this.shown.size;
    all.indeterminate = chosen.length > 0 && chosen.length < this.shown.size;
  },

  // The split's options in a dialog, then one run per file. For one file the
  // levels say how many bookmarks each has, which is about how many sections
  // that level makes.
  async split( chosen ) {
    const files = chosen.filter( ( file ) => this.splittable( file ) );
    if ( files.length === 0 ) return;
    const depth = Math.max( ...files.map( ( file ) => file.levels.length ) );
    const levels = Array.from( { length: depth } , ( unused , index ) => {
      const label = I18n.get( "split.level_option" ).replace( "{level}" , index + 1 );
      const counts = files.length === 1 ? I18n.get( "split.level_count" ).replace( "{count}" , files[ 0 ].levels[ index ] ) : "";
      return { value: String( index + 1 ) , label: label + counts };
    } );
    const title = files.length === 1
      ? I18n.get( "split.title_one" ).replace( "{name}" , files[ 0 ].name )
      : I18n.get( "split.title_many" ).replace( "{count}" , files.length );
    const started = await Dom.form( {
      title: title,
      submit: I18n.get( "split.start" ),
      fields: [
        { name: "level" , label: I18n.get( "split.level" ) , type: "select" , options: levels , value: "1" , help: I18n.get( "split.level_help" ) },
        { name: "front_matter" , label: I18n.get( "split.front_matter" ) , type: "checkbox" , value: true },
        { name: "inner_bookmarks" , label: I18n.get( "split.inner_bookmarks" ) , type: "checkbox" , value: true },
        { name: "numbered" , label: I18n.get( "split.numbered" ) , type: "checkbox" , value: true },
      ],
      save: async ( values ) => {
        const options = Object.assign( {} , values , { level: Number( values.level ) } );
        // One request for any number of files, so a folder's worth stays
        // within the rate limit.
        const started = await Api.startActionMany( files.map( ( file ) => file.id ) , "split_bookmarks" , options );
        return started.runs.length;
      },
    } );
    if ( !started ) return;
    this.selected.clear();
    this.paintSelection();
    Dom.all( "#files-table tbody input[type=checkbox]" ).forEach( ( box ) => { box.checked = false; } );
    Dom.toast( I18n.get( "split.started" ).replace( "{count}" , started ) , "ok" , {
      text: I18n.get( "split.see_runs" ),
      run: () => Nav.show( "runs" ),
    } );
  },
};

// Sizes, as every screen words them.
const Files = {
  size( bytes ) {
    const units = [ [ 1 << 30 , "files.size_gb" ] , [ 1 << 20 , "files.size_mb" ] , [ 1 << 10 , "files.size_kb" ] ];
    for ( const [ scale , key ] of units ) {
      if ( bytes >= scale ) return I18n.get( key ).replace( "{count}" , ( bytes / scale ).toFixed( 1 ) );
    }
    return I18n.get( "files.size_b" ).replace( "{count}" , String( Math.round( bytes ) ) );
  },
};
