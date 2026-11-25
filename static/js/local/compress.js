// Compress, in the browser: app/actions/compress.py's lossless level with
// qpdf's own flags. The images level needs Pillow, so it runs on the server
// only (local.js sends it there).
const LocalCompress = {
  DEFAULTS: { level: "lossless" , image_dpi: 150 },

  // Whether these options can run here at all.
  supports( options ) {
    return ( options && options.level || "lossless" ) === "lossless";
  },

  async run( qpdf , source , work , options , hooks , sourceName ) {
    const pages = ( typeof LocalPages !== "undefined" ? LocalPages : require( "./pages.js" ).LocalPages );
    options = Object.assign( {} , this.DEFAULTS , options );
    if ( !this.supports( options ) ) throw new Error( "server_only" );
    hooks.progress( 0 , "" );
    const pageCount = LocalSplit.pageCount( qpdf , source );
    const before = pages.size( qpdf , source );
    const target = work + "/" + ( hooks.prefix || "" ) + "compressed.pdf";
    await qpdf.prepare( target );
    qpdf.ok( [ source , "--compress-streams=y" , "--recompress-flate" , "--compression-level=9" , "--decode-level=generalized" ,
      "--object-streams=generate" , "--remove-unreferenced-resources=yes" , target ] );
    let after = pages.size( qpdf , target );
    if ( after >= before ) {
      // Nothing to gain: the file as it was, so a chain never grows it.
      qpdf.remove( target );
      await pages.copy( qpdf , source , target );
      after = before;
    }
    const name = pages.stem( sourceName ) + " - compressed.pdf";
    await hooks.output( name , target , { pages: pageCount , first_page: 1 , last_page: pageCount , title: "" } );
    hooks.progress( 1 , name );
    return { before: before , after: after , images: 0 };
  },
};

if ( typeof module !== "undefined" && module.exports ) module.exports = { LocalCompress };
