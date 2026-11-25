// The Runs screen: every action started on a PDF, how far it has got, and the
// files it made, to download one at a time or all together as a zip.
//
// It also owns the page's one stream from the server (/api/runs/stream),
// which says "runs" when a run moves and "files" when an import has been read.
// Each is passed on as a window event (work:runs, work:files), so the Library
// hears it too without a second connection.
const Runs = {
  me: null,
  // The runs whose sections are shown under them.
  open: new Set(),
  // The last read of each open run's files.
  details: new Map(),
  // What is ticked in each open run's watermark findings (js/watermarks.js).
  picks: new Map(),
  // At most one read per this, and the last change always gets one. A run
  // moves often; the general rate limit (120 a minute) is shared with
  // everything else the page does.
  everyMs: 2000,

  async init( me ) {
    this.me = me;
    if ( me.files_enabled === false ) return;
    Pager.sortable( "runs-table" , () => this.refresh() );
    Pager.search( "runs-table" , "runs-search" , () => this.refresh() );
    window.addEventListener( "work:runs" , () => this.refreshSoon() );
    // Changes heard while another screen showed are read on coming back.
    window.addEventListener( "nav" , ( event ) => {
      if ( event.detail.screen === "runs" && this.stale ) this.refreshSoon();
    } );
    this.listen();
    await this.refresh();
  },

  // Open only while the tab is showing. A browser allows six connections to
  // one server, shared by every tab, and a stream holds one for as long as it
  // is open: a few background tabs would otherwise leave none for the tab in
  // use. Coming back, both screens read what they missed.
  listen() {
    if ( typeof EventSource === "undefined" ) return;
    const open = () => {
      if ( this.source ) return;
      const source = new EventSource( Api.workStreamPath() );
      [ "runs" , "files" ].forEach( ( name ) => source.addEventListener( name , () => {
        window.dispatchEvent( new Event( "work:" + name ) );
      } ) );
      this.source = source;
    };
    const close = () => {
      if ( this.source ) this.source.close();
      this.source = null;
    };
    document.addEventListener( "visibilitychange" , () => {
      if ( document.visibilityState === "hidden" ) {
        close();
        return;
      }
      open();
      window.dispatchEvent( new Event( "work:runs" ) );
      window.dispatchEvent( new Event( "work:files" ) );
    } );
    if ( document.visibilityState !== "hidden" ) open();
  },

  refreshSoon() {
    if ( !Dom.get( "runs-panel" ).classList.contains( "view-active" ) ) {
      this.stale = true;
      return;
    }
    this.stale = false;
    if ( this.timer ) return;
    const wait = Math.max( 0 , ( this.last || 0 ) + this.everyMs - Date.now() );
    this.timer = window.setTimeout( () => {
      this.timer = null;
      this.last = Date.now();
      this.refresh();
    } , wait );
  },

  async refresh() {
    const params = Pager.params( "runs-table" );
    const page = await Pager.load( "runs-table" , "runs" , ( offset ) => Api.runs( offset , params ) , ( one ) => this.renderRow( one ) );
    if ( !page ) return;
    // The files of each open run, read again; until they come, the last ones
    // read stay in place, so nothing jumps.
    for ( const id of [ ...this.open ] ) {
      const holder = Dom.get( "runs-table" ).querySelector( "tr[data-sections='" + id + "'] td" );
      if ( !holder ) {
        this.open.delete( id );
        continue;
      }
      try {
        this.details.set( id , await Api.run( id ) );
      } catch ( error ) {
        this.details.delete( id );
      }
      Dom.swap( holder , this.sectionsList( this.details.get( id ) ) );
    }
  },

  renderRow( one ) {
    const body = Dom.get( "runs-table" ).querySelector( "tbody" );
    body.appendChild( this.row( one ) );
    if ( this.open.has( one.id ) ) {
      body.appendChild( Dom.el( "tr" , { class: "runs-sections" , attrs: { "data-sections": one.id } , children: [
        Dom.el( "td" , { attrs: { colspan: "6" } , children: [ this.sectionsList( this.details.get( one.id ) ) ] } ),
      ] } ) );
    }
  },

  stateCell( one ) {
    const tones = { queued: "secondary" , running: "primary" , done: "success" , failed: "danger" , cancelled: "secondary" };
    const children = [ Dom.badge( I18n.get( "runs.state_" + one.state ) , tones[ one.state ] ) ];
    if ( one.state === "running" || one.state === "queued" ) {
      const bar = Dom.el( "progress" , { class: "w-100 d-block mt-1" , attrs: { max: "1" , value: String( one.progress ) , "aria-label": I18n.get( "runs.progress_label" ) } } );
      children.push( bar );
      if ( one.step ) children.push( Dom.el( "div" , { class: "small text-body-secondary text-break" , text: one.step } ) );
    }
    if ( one.state === "failed" ) {
      children.push( Dom.el( "div" , { class: "small text-danger" , text: I18n.get( "runs.errors." + one.message ) || one.message } ) );
    }
    if ( one.state === "done" && one.result ) {
      const notes = [];
      if ( one.result.folded ) notes.push( I18n.get( "runs.folded" ).replace( "{count}" , one.result.folded ) );
      if ( one.result.nowhere ) notes.push( I18n.get( "runs.nowhere" ).replace( "{count}" , one.result.nowhere ) );
      if ( this.hasFindings( one ) ) notes.push( Watermarks.note( one.result , "runs" ) );
      if ( notes.length ) children.push( Dom.el( "div" , { class: "small text-body-secondary" , text: notes.join( " " ) } ) );
    }
    return children;
  },

  actionText( one ) {
    const text = ToolOptions.summary( one.action , one.options );
    return one.chain_id ? text + " · " + I18n.get( "runs.chain_step" ).replace( "{step}" , one.step_index + 1 ) : text;
  },

  row( one ) {
    const finished = [ "done" , "failed" , "cancelled" ].includes( one.state );
    const toggle = one.outputs > 0 || this.hasFindings( one ) ? Dom.el( "button" , {
      class: "btn btn-sm btn-outline-secondary",
      text: I18n.get( this.open.has( one.id ) ? "runs.hide_button" : "runs.show_button" ),
      attrs: { "aria-expanded": String( this.open.has( one.id ) ) },
      on: { click: () => this.toggle( one ) },
    } ) : null;
    const zip = one.outputs > 0 ? Dom.el( "a" , {
      class: "btn btn-sm btn-primary",
      attrs: { href: Api.runDownloadPath( one.id ) , download: "" },
      children: [
        Dom.el( "i" , { class: "bi bi-file-earmark-zip me-1" , attrs: { "aria-hidden": "true" } } ),
        Dom.el( "span" , { text: I18n.get( "runs.zip_button" ) } ),
      ],
    } ) : null;
    const cancel = !finished ? Dom.el( "button" , {
      class: "btn btn-sm btn-outline-secondary",
      text: I18n.get( "ui.cancel" ),
      on: { click: () => this.cancel( one ) },
    } ) : null;
    // A chain's step starts again with its chain, on the chain's screen.
    const restart = [ "cancelled" , "failed" ].includes( one.state ) && !one.chain_id ? Dom.el( "button" , {
      class: "btn btn-sm btn-outline-primary",
      children: [
        Dom.el( "i" , { class: "bi bi-arrow-clockwise me-1" , attrs: { "aria-hidden": "true" } } ),
        Dom.el( "span" , { text: I18n.get( "runs.restart_button" ) } ),
      ],
      on: { click: () => this.restart( one ) },
    } ) : null;
    const remove = Dom.el( "button" , {
      class: "btn btn-sm btn-outline-danger",
      text: I18n.get( "runs.delete_button" ),
      on: { click: () => this.remove( one ) },
    } );
    const made = one.outputs > 0
      ? I18n.get( "runs.made" ).replace( "{count}" , one.outputs ).replace( "{size}" , Files.size( one.output_bytes ) )
      : "";
    return Dom.el( "tr" , { attrs: { "data-run": one.id } , children: [
      Dom.el( "td" , { class: "text-break cell-name" , text: one.file_name } ),
      Dom.el( "td" , { text: this.actionText( one ) } ),
      Dom.el( "td" , { class: "runs-state" , children: this.stateCell( one ) } ),
      Dom.el( "td" , { class: "text-nowrap" , text: made } ),
      Dom.el( "td" , { class: "text-nowrap" , children: [ Dom.when( one.created_at ) ] } ),
      Dom.el( "td" , { class: "text-nowrap" , children: [ Dom.rowActions( one.file_name , [ zip , restart , toggle , cancel , remove ] , 2 ) ] } ),
    ] } );
  },

  // The run's files, listed in a row of their own under it.
  sectionsList( detail ) {
    const items = ( detail ? detail.files : [] ).map( ( file ) => Dom.el( "li" , { class: "list-group-item d-flex flex-wrap align-items-center gap-2 px-0" , children: [
      Dom.el( "i" , { class: "bi bi-file-earmark-pdf text-body-secondary" , attrs: { "aria-hidden": "true" } } ),
      Dom.el( "span" , { class: "text-break flex-grow-1" , text: file.name } ),
      Dom.el( "span" , { class: "small text-body-secondary text-nowrap" , text: I18n.get( "runs.section_pages" ).replace( "{count}" , file.pages ) } ),
      Dom.el( "span" , { class: "small text-body-secondary text-nowrap" , text: Files.size( file.size ) } ),
      Dom.el( "a" , {
        class: "btn btn-sm btn-outline-secondary",
        text: I18n.get( "files.download_button" ),
        attrs: { href: Api.fileDownloadPath( file.id ) , download: file.name },
      } ),
    ] } ) );
    if ( !detail ) items.push( Dom.el( "li" , { class: "list-group-item px-0 text-body-secondary" , text: I18n.get( "runs.loading" ) } ) );
    const list = Dom.el( "ul" , { class: "list-group list-group-flush small" , children: items } );
    if ( !detail || !this.hasFindings( detail ) ) return list;
    if ( !this.picks.has( detail.id ) ) this.picks.set( detail.id , Watermarks.state( detail.result ) );
    const panel = Dom.el( "div" , { class: "small" , children: [
      Watermarks.panel( detail.result , this.picks.get( detail.id ) , ( ids ) => this.removePicked( detail , ids ) ),
    ] } );
    return Dom.el( "div" , { children: items.length ? [ list , panel ] : [ panel ] } );
  },

  hasFindings( one ) {
    return one.action === "remove_watermarks" && one.state === "done" && one.result && Array.isArray( one.result.findings );
  },

  // A new remove run on the same PDF, taking out the findings ticked.
  async removePicked( detail , ids ) {
    const options = Object.assign( {} , detail.options || {} , { mode: "remove" , picked: ids } );
    try {
      const started = await Api.startActionMany( [ detail.file_id ] , "remove_watermarks" , options );
      if ( started.skipped.length ) {
        const why = started.skipped[ 0 ].error;
        App.showError( I18n.get( "runs.errors." + why ) || why );
        return;
      }
      Dom.toast( I18n.get( "watermarks.started" ) , "ok" );
    } catch ( error ) {
      App.showError( error.message );
    }
    await this.refresh();
  },

  async toggle( one ) {
    if ( this.open.has( one.id ) ) this.open.delete( one.id );
    else this.open.add( one.id );
    await this.refresh();
  },

  async cancel( one ) {
    try {
      await Api.cancelRun( one.id );
    } catch ( error ) {
      App.showError( error.message );
    }
    await this.refresh();
  },

  async restart( one ) {
    try {
      await Api.restartRun( one.id );
    } catch ( error ) {
      App.showError( error.message );
    }
    await this.refresh();
  },

  async remove( one ) {
    try {
      await Api.deleteRun( one.id );
      this.open.delete( one.id );
      await this.refresh();
    } catch ( error ) {
      App.showError( error.message );
      return;
    }
    Undo.record( {
      label: I18n.get( "undo.deleted_run" ),
      toast: true,
      undo: async () => { await Api.restoreRun( one.id ); await this.refresh(); },
      redo: async () => { await Api.deleteRun( one.id ); await this.refresh(); },
    } );
  },
};
