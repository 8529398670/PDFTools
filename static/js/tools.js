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
// else Automatic. Tools.mode answers that; Tools.where resolves Automatic on
// this device.
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
      { id: "compress" , icon: "bi-file-zip" },
      { id: "rotate" , icon: "bi-arrow-clockwise" },
      { id: "crop" , icon: "bi-crop" },
      { id: "protect" , icon: "bi-lock" },
      { id: "unprotect" , icon: "bi-unlock" },
      { id: "repair" , icon: "bi-wrench-adjustable" },
    ] },
  ],
  modes: [ "auto" , "device" , "server" ],
  engines: [ "device" , "server" ],
  me: null,

  init( me ) {
    this.me = me;
    Dom.show( Dom.get( "tools-panel" ) , true );
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

  // Where it would run on this device now: "device" or "server".
  where( id ) {
    const device = Local.device();
    const mode = this.mode( id );
    if ( !device.supported || mode === "server" ) return "server";
    if ( mode === "device" ) return "device";
    return device.capable ? "device" : "server";
  },

  // After Account saved new modes: the badges here and the tool screens follow.
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
      children: section.tools.map( ( tool ) => Dom.el( "div" , { class: "col" , children: [ this.toolCard( tool ) ] } ) ),
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
    const badges = Dom.el( "div" , { class: "d-flex flex-wrap gap-1 mt-2" } );
    if ( tool.ready ) {
      const here = this.where( tool.id ) === "device";
      badges.appendChild( Dom.el( "span" , {
        class: "badge " + ( here ? "text-bg-success" : "text-bg-info" ),
        children: [
          Dom.el( "i" , { class: "bi me-1 " + ( here ? "bi-cpu" : "bi-cloud" ) , attrs: { "aria-hidden": "true" } } ),
          document.createTextNode( I18n.get( here ? "tools.where_device" : "tools.where_server" ) ),
        ],
      } ) );
    } else {
      badges.appendChild( Dom.badge( I18n.get( "tools.todo" ) , "warning" ) );
    }
    const body = Dom.el( "div" , {
      class: "card-body d-flex gap-3",
      children: [
        Dom.el( "i" , { class: "bi " + tool.icon + " fs-3 tool-icon" , attrs: { "aria-hidden": "true" } } ),
        Dom.el( "div" , {
          class: "flex-grow-1",
          children: [
            Dom.el( "h4" , { class: "h6 card-title mb-1" , text: this.title( tool.id ) } ),
            Dom.el( "p" , { class: "card-text small text-body-secondary mb-0" , text: I18n.get( "tools.items." + tool.id + ".help" ) } ),
            badges,
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
