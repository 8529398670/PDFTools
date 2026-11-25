// What a PDF link does, the account's choice (me.pdf_links, saved with POST
// /api/account/pdf-links so it follows the person to every device):
// - "open" (the default): a new tab, in the browser's own PDF viewer. A
//   server file links to GET /api/files/<id>/view, which sends a PDF inline;
//   a file made in this page is a blob: URL typed application/pdf. The
//   browser decides whether a new tab comes to the front; Cmd/Ctrl-click
//   keeps it behind.
// - "download": saved, as every link did before (.../download, or a blob:
//   URL with the download attribute).
// Zips are always downloads. See app/models/pdf_links.py.
const PdfLinks = {
  choice: "open",
  // Links drawn with attrs(), redrawn when the choice changes.
  drawn: new Set(),

  init( me ) {
    this.choice = me.pdf_links === "download" ? "download" : "open";
    Dom.show( Dom.get( "pdf-links-panel" ) , true );
    this.paint();
    Dom.all( "input[name='pdf-links']" ).forEach( ( input ) => {
      input.addEventListener( "change" , async () => {
        if ( !input.checked ) return;
        const previous = this.choice;
        try {
          const reply = await Api.setPdfLinks( input.value );
          this.set( reply.pdf_links );
          Dom.toast( I18n.get( "pdf_links.saved" ) , "ok" );
        } catch ( error ) {
          this.set( previous );
          App.showError( error.message );
        }
      } );
    } );
  },

  opens() {
    return this.choice !== "download";
  },

  set( choice ) {
    this.choice = choice === "download" ? "download" : "open";
    this.paint();
    this.drawn.forEach( ( link ) => {
      if ( !link.isConnected ) this.drawn.delete( link );
      else this.apply( link );
    } );
  },

  paint() {
    const input = Dom.get( "pdf-links-" + this.choice );
    if ( input ) input.checked = true;
  },

  // Points a link at a PDF the way the account wants. Each link carries both
  // addresses (data-view and data-download) and its name, so a change of
  // choice can redraw it in place.
  link( link , view , download , name ) {
    link.dataset.view = view;
    link.dataset.download = download;
    link.dataset.name = name || "";
    this.drawn.add( link );
    this.apply( link );
    return link;
  },

  apply( link ) {
    if ( this.opens() ) {
      link.href = link.dataset.view;
      link.target = "_blank";
      link.rel = "noopener";
      link.removeAttribute( "download" );
    } else {
      link.href = link.dataset.download;
      link.removeAttribute( "target" );
      link.removeAttribute( "rel" );
      link.download = link.dataset.name;
    }
    // A button-styled link says what it does.
    if ( link.dataset.label === "button" ) Dom.text( link , I18n.get( this.opens() ? "pdf_links.open_button" : "files.download_button" ) );
  },

  // Renames a drawn link's file.
  rename( link , name ) {
    link.dataset.name = name;
    this.apply( link );
  },

  // A blob: URL that a browser will show rather than save: the same bytes,
  // typed application/pdf (a file read back from OPFS has no type).
  viewUrl( file ) {
    return URL.createObjectURL( file.type === "application/pdf" ? file : new Blob( [ file ] , { type: "application/pdf" } ) );
  },

  // Opens or saves a URL now, as a click on a link would. Only from a press:
  // a browser blocks a new tab opened any other time.
  follow( view , download , name ) {
    const link = Dom.el( "a" , {} );
    this.link( link , view , download , name );
    this.drawn.delete( link );
    document.body.appendChild( link );
    link.click();
    link.remove();
  },
};
