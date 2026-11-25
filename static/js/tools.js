// Tools, the home page: every tool this app has or will have, one collapsed
// accordion row per section. A tool that is built opens its own screen
// (data-path /tools/<id with dashes>); the rest carry a TODO badge.
//
// The catalog here is the one list of tools for the page. Its ids match
// app.actions.TOOL_IDS on the server, which checks run-mode overrides against
// it, and language.yaml's tools.items.<id>. A tool's engines say where it can
// run at all: "device" (qpdf as WebAssembly in this page) and "server".
//
// Where a tool runs is the account's choice (me.tool_modes, set on Account
// with js/tool_modes.js): its own override, else the account's default ("*"),
// else Automatic. Tools.mode answers that. Where it runs is never shown on
// the cards: the choice lives on Account.
const Tools = {
  catalog: [
    { id: "split" , tools: [
      { id: "extract_pages" , icon: "bi-file-earmark-arrow-up" },
      { id: "delete_pages" , icon: "bi-file-earmark-x" },
      { id: "split_bookmarks" , icon: "bi-bookmarks" , ready: true },
      { id: "split_pages" , icon: "bi-layout-split" },
      { id: "split_size" , icon: "bi-rulers" },
      { id: "split_text" , icon: "bi-fonts" },
    ] },
    { id: "merge" , tools: [
      { id: "alternate_mix" , icon: "bi-shuffle" },
      { id: "visual_combine" , icon: "bi-grid-3x3-gap" },
      { id: "merge" , icon: "bi-union" },
    ] },
    { id: "convert" , tools: [
      { id: "extract_text" , icon: "bi-file-earmark-text" },
      { id: "grayscale" , icon: "bi-circle-half" },
      { id: "images_to_pdf" , icon: "bi-images" },
    ] },
    { id: "other" , tools: [
      { id: "compress" , icon: "bi-file-zip" , ready: true },
      { id: "rotate" , icon: "bi-arrow-clockwise" , ready: true },
      { id: "remove_watermarks" , icon: "bi-droplet-half" , ready: true },
      { id: "crop" , icon: "bi-crop" },
      { id: "protect" , icon: "bi-lock" },
      { id: "unprotect" , icon: "bi-unlock" },
      { id: "repair" , icon: "bi-wrench-adjustable" },
    ] },
    { id: "chain" , tools: [
      { id: "chain" , icon: "bi-link-45deg" , ready: true },
    ] },
  ],
  modes: [ "auto" , "device" , "server" ],
  engines: [ "device" , "server" ],
  me: null,
  beforeSearch: null,

  init( me ) {
    this.me = me;
    Dom.show( Dom.get( "tools-panel" ) , true );
    Dom.get( "tools-search" ).addEventListener( "input" , () => this.applySearch() );
    Dom.onPress( Dom.get( "tools-expand-all" ) , () => this.toggleAll( true ) );
    Dom.onPress( Dom.get( "tools-collapse-all" ) , () => this.toggleAll( false ) );
    this.render();
    // The tool screens have no sidebar link of their own: Tools stays lit.
    window.addEventListener( "nav" , ( event ) => {
      if ( !event.detail.screen.startsWith( "tool-" ) ) return;
      const link = document.querySelector( '[data-nav="tools"]' );
      if ( link ) link.classList.add( "active" );
    } );
  },

  all() {
    return this.catalog.flatMap( ( section ) => section.tools.map( ( tool ) => Object.assign( { section: section.id } , tool ) ) );
  },

  find( id ) {
    return this.all().find( ( tool ) => tool.id === id ) || null;
  },

  path( id ) {
    return "/tools/" + id.replace( /_/g , "-" );
  },

  title( id ) {
    return I18n.get( "tools.items." + id + ".title" );
  },

  // ---- where a tool runs ---------------------------------------------------

  saved() {
    return ( this.me && this.me.tool_modes ) || {};
  },

  defaultMode() {
    const value = this.saved()[ "*" ];
    return this.modes.includes( value ) ? value : "auto";
  },

  // The account's choice for this tool: auto, device or server.
  mode( id ) {
    const value = this.saved()[ id ];
    return this.modes.includes( value ) ? value : this.defaultMode();
  },

  modeLabel( mode ) {
    return I18n.get( "tool_modes." + mode );
  },

  // After Account saved new modes: the tool screens follow.
  changed( modes ) {
    if ( this.me ) this.me.tool_modes = modes;
    this.render();
  },

  // ---- the page ------------------------------------------------------------

  render() {
    const holder = Dom.get( "tools-sections" );
    // Rows the reader opened stay open across a redraw; on load all are shut.
    const open = new Set( Dom.all( ".accordion-collapse.show" , holder ).map( ( node ) => node.id ) );
    Dom.clear( holder );
    this.catalog.forEach( ( section ) => holder.appendChild( this.sectionRow( section , open ) ) );
    this.applySearch();
  },

  // ---- search, expand and collapse -----------------------------------------

  // Every word typed must appear in a tool's title, help or section name.
  // While a search is on, sections with a match are open and the rest are
  // hidden; clearing it puts back the rows that were open before.
  applySearch() {
    const holder = Dom.get( "tools-sections" );
    const words = Dom.get( "tools-search" ).value.trim().toLowerCase().split( /\s+/ ).filter( Boolean );
    const searching = words.length > 0;
    if ( searching && !this.beforeSearch ) {
      this.beforeSearch = new Set( Dom.all( ".accordion-collapse.show" , holder ).map( ( node ) => node.id ) );
    }
    let shown = 0;
    let total = 0;
    Dom.all( ".accordion-item" , holder ).forEach( ( item ) => {
      let matches = 0;
      Dom.all( "[data-words]" , item ).forEach( ( col ) => {
        const hit = words.every( ( word ) => col.getAttribute( "data-words" ).includes( word ) );
        Dom.show( col , hit );
        total += 1;
        if ( hit ) matches += 1;
      } );
      shown += matches;
      Dom.show( item , matches > 0 );
      const collapse = item.querySelector( ".accordion-collapse" );
      if ( searching ) this.setOpen( collapse , matches > 0 );
      else if ( this.beforeSearch ) this.setOpen( collapse , this.beforeSearch.has( collapse.id ) );
    } );
    if ( !searching ) this.beforeSearch = null;
    Dom.text( Dom.get( "tools-search-status" ) , searching
      ? I18n.get( "tools.search_count" ).replace( "{count}" , shown ).replace( "{total}" , total )
      : "" );
    Dom.show( Dom.get( "tools-search-none" ) , searching && shown === 0 );
  },

  // Opens or shuts a section at once, with no animation (search redraws).
  setOpen( collapse , open ) {
    collapse.classList.toggle( "show" , open );
    const button = document.querySelector( '[data-bs-target="#' + collapse.id + '"]' );
    if ( !button ) return;
    button.classList.toggle( "collapsed" , !open );
    button.setAttribute( "aria-expanded" , String( open ) );
  },

  // Expand all / Collapse all: every section the search leaves showing.
  toggleAll( open ) {
    Dom.all( "#tools-sections .accordion-item" ).forEach( ( item ) => {
      if ( item.hidden ) return;
      const instance = bootstrap.Collapse.getOrCreateInstance( item.querySelector( ".accordion-collapse" ) , { toggle: false } );
      if ( open ) instance.show(); else instance.hide();
    } );
  },

  sectionRow( section , open ) {
    const id = "tools-section-" + section.id;
    const shown = open.has( id );
    const ready = section.tools.filter( ( tool ) => tool.ready ).length;
    const button = Dom.el( "button" , {
      class: "accordion-button" + ( shown ? "" : " collapsed" ),
      attrs: { type: "button" , "data-bs-toggle": "collapse" , "data-bs-target": "#" + id , "aria-expanded": String( shown ) , "aria-controls": id , "data-scroll": "free" },
      children: [
        Dom.el( "span" , { class: "fw-semibold me-2" , text: I18n.get( "tools.sections." + section.id ) } ),
        Dom.el( "span" , { class: "badge text-bg-light border me-2" , text: I18n.get( "tools.count" ).replace( "{count}" , section.tools.length ) } ),
      ],
    } );
    if ( ready < section.tools.length ) button.appendChild( Dom.badge( I18n.get( "tools.todo" ) + " " + ( section.tools.length - ready ) , "warning" ) );
    const grid = Dom.el( "div" , {
      class: "row row-cols-1 row-cols-md-2 row-cols-xl-3 g-3",
      children: section.tools.map( ( tool ) => Dom.el( "div" , {
        class: "col",
        attrs: { "data-words": [ this.title( tool.id ) , I18n.get( "tools.items." + tool.id + ".help" ) , I18n.get( "tools.sections." + section.id ) ].join( " " ).toLowerCase() },
        children: [ this.toolCard( tool ) ],
      } ) ),
    } );
    return Dom.el( "div" , {
      class: "accordion-item",
      children: [
        Dom.el( "h3" , { class: "accordion-header" , children: [ button ] } ),
        Dom.el( "div" , {
          class: "accordion-collapse collapse" + ( shown ? " show" : "" ),
          attrs: { id: id },
          children: [ Dom.el( "div" , { class: "accordion-body" , children: [ grid ] } ) ],
        } ),
      ],
    } );
  },

  toolCard( tool ) {
    const badges = tool.ready ? null : Dom.el( "div" , { class: "d-flex flex-wrap gap-1 mt-2" , children: [ Dom.badge( I18n.get( "tools.todo" ) , "warning" ) ] } );
    const body = Dom.el( "div" , {
      class: "card-body d-flex gap-3",
      children: [
        Dom.el( "i" , { class: "bi " + tool.icon + " fs-3 tool-icon" , attrs: { "aria-hidden": "true" } } ),
        Dom.el( "div" , {
          class: "flex-grow-1",
          children: [
            Dom.el( "h4" , { class: "h6 card-title mb-1" , text: this.title( tool.id ) } ),
            Dom.el( "p" , { class: "card-text small text-body-secondary mb-0" , text: I18n.get( "tools.items." + tool.id + ".help" ) } ),
            ...( badges ? [ badges ] : [] ),
          ],
        } ),
      ],
    } );
    if ( !tool.ready ) {
      return Dom.el( "div" , { class: "card h-100 tool-card tool-card-todo" , attrs: { "aria-disabled": "true" } , children: [ body ] } );
    }
    // The whole card is the link to the tool's screen (Nav follows it).
    return Dom.el( "a" , {
      class: "card h-100 tool-card text-decoration-none text-reset",
      attrs: { href: this.path( tool.id ) },
      children: [ body ],
    } );
  },
};
