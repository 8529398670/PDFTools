// Rotate, in the browser: app/actions/rotate.py with qpdf's --rotate, which
// changes only each page's /Rotate, as pikepdf's page.rotate does.
const LocalRotate = {
  DEFAULTS: { angle: 90 , pages: "all" },

  async run( qpdf , source , work , options , hooks , sourceName ) {
    const pages = ( typeof LocalPages !== "undefined" ? LocalPages : require( "./pages.js" ).LocalPages );
    options = Object.assign( {} , this.DEFAULTS , options );
    hooks.progress( 0 , "" );
    const pageCount = LocalSplit.pageCount( qpdf , source );
    const chosen = pages.parse( options.pages , pageCount );
    const target = work + "/" + ( hooks.prefix || "" ) + "rotated.pdf";
    await qpdf.prepare( target );
    qpdf.ok( [ source , "--rotate=+" + options.angle + ":" + pages.ranges( chosen ) , "--decode-level=none" , "--object-streams=preserve" , target ] );
    const name = pages.stem( sourceName ) + " - rotated.pdf";
    await hooks.output( name , target , { pages: pageCount , first_page: 1 , last_page: pageCount , title: "" } );
    hooks.progress( 1 , name );
    return { pages: chosen.length , angle: options.angle };
  },
};

if ( typeof module !== "undefined" && module.exports ) module.exports = { LocalRotate };
