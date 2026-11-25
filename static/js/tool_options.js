// Each tool's options: the dialog a tool screen asks before it runs
// (js/local.js), the form a chain's step is set with (js/chain.js), and the
// short words the Runs list and a chain's steps show them with. The values
// and their defaults are the server's (app/actions/<name>.py Options); the
// browser twins take the same ones (js/local/<name>.js).
const ToolOptions = {
  defaults: {
    split_bookmarks: { level: 1 , front_matter: true , inner_bookmarks: true , numbered: true },
    rotate: { angle: 90 , pages: "all" },
    compress: { level: "lossless" , image_dpi: 150 },
  },

  // The tools a chain can hold, in the order its picker lists them.
  chainable: [ "rotate" , "split_bookmarks" , "compress" ],

  // How deep a chain's split may go, since it cannot look at the PDF first.
  chainLevels: 6,

  name( action ) {
    return I18n.get( "actions." + action + ".name" ) || action;
  },

  merged( action , options ) {
    return Object.assign( {} , this.defaults[ action ] || {} , options || {} );
  },

  // Whether these options can run in this browser at all (compress's
  // picture shrinking needs the server's Pillow).
  onDevice( action , options ) {
    if ( action === "compress" ) return this.merged( action , options ).level === "lossless";
    return Boolean( this.defaults[ action ] );
  },

  // Words for the options: "Rotate · 90°, pages all".
  summary( action , options ) {
    const name = this.name( action );
    const chosen = this.merged( action , options );
    if ( action === "split_bookmarks" ) return name + " · " + I18n.get( "actions.split_bookmarks.summary" ).replace( "{level}" , chosen.level );
    if ( action === "rotate" ) {
      return name + " · " + I18n.get( "actions.rotate.summary" ).replace( "{angle}" , chosen.angle ).replace( "{pages}" , chosen.pages || "all" );
    }
    if ( action === "compress" ) {
      return name + " · " + ( chosen.level === "images"
        ? I18n.get( "actions.compress.summary_images" ).replace( "{dpi}" , chosen.image_dpi )
        : I18n.get( "actions.compress.summary_lossless" ) );
    }
    return name;
  },

  // Dom.form fields for action, starting from options. jobs, on a tool
  // screen, are the PDFs it will run on, with what reading them found
  // (job.info.levels): a split then offers only levels they have.
  fields( action , options , jobs ) {
    const chosen = this.merged( action , options );
    if ( action === "split_bookmarks" ) {
      const known = jobs && jobs.length && jobs.every( ( job ) => job.info && job.info.levels );
      const depth = known ? Math.max( 1 , ...jobs.map( ( job ) => job.info.levels.length ) ) : this.chainLevels;
      const levels = Array.from( { length: depth } , ( unused , index ) => {
        const label = I18n.get( "split.level_option" ).replace( "{level}" , index + 1 );
        const counts = known && jobs.length === 1 ? I18n.get( "split.level_count" ).replace( "{count}" , jobs[ 0 ].info.levels[ index ] ) : "";
        return { value: String( index + 1 ) , label: label + counts };
      } );
      return [
        { name: "level" , label: I18n.get( "split.level" ) , type: "select" , options: levels , value: String( Math.min( chosen.level , depth ) ) ,
          help: I18n.get( known ? "split.level_help" : "options.split_level_help" ) },
        { name: "front_matter" , label: I18n.get( "split.front_matter" ) , type: "checkbox" , value: chosen.front_matter },
        { name: "inner_bookmarks" , label: I18n.get( "split.inner_bookmarks" ) , type: "checkbox" , value: chosen.inner_bookmarks },
        { name: "numbered" , label: I18n.get( "split.numbered" ) , type: "checkbox" , value: chosen.numbered },
      ];
    }
    if ( action === "rotate" ) {
      return [
        { name: "angle" , label: I18n.get( "options.angle" ) , type: "select" , value: String( chosen.angle ) , options: [ 90 , 180 , 270 ].map( ( angle ) => (
          { value: String( angle ) , label: I18n.get( "options.angle_" + angle ) } ) ) },
        { name: "pages" , label: I18n.get( "options.pages" ) , value: chosen.pages === "all" ? "" : chosen.pages , maxLength: 500 ,
          placeholder: "1-3, 7, 10-" , help: I18n.get( "options.pages_help" ) },
      ];
    }
    if ( action === "compress" ) {
      return [
        { name: "level" , label: I18n.get( "options.level" ) , type: "select" , value: chosen.level , options: [ "lossless" , "images" ].map( ( level ) => (
          { value: level , label: I18n.get( "options.level_" + level ) } ) ) },
        { name: "image_dpi" , label: I18n.get( "options.image_dpi" ) , type: "number" , min: 50 , max: 600 , value: chosen.image_dpi ,
          help: I18n.get( "options.image_dpi_help" ) },
      ];
    }
    return [];
  },

  // What the form answered, as the action's options.
  read( action , values ) {
    if ( action === "split_bookmarks" ) return Object.assign( {} , values , { level: Number( values.level ) } );
    if ( action === "rotate" ) return { angle: Number( values.angle ) , pages: String( values.pages || "" ).trim() || "all" };
    if ( action === "compress" ) return { level: values.level , image_dpi: Number( values.image_dpi ) || 150 };
    return values;
  },

  // The dialog before a tool screen runs action on jobs: its options, or
  // null if it was cancelled.
  async ask( action , jobs , options ) {
    const prefix = action === "split_bookmarks" ? "split." : "options." + action + "_";
    const title = jobs.length === 1
      ? I18n.get( prefix + "title_one" ).replace( "{name}" , jobs[ 0 ].file.name )
      : I18n.get( prefix + "title_many" ).replace( "{count}" , jobs.length );
    let chosen = null;
    const answered = await Dom.form( {
      title: title,
      submit: I18n.get( action === "split_bookmarks" ? "split.start" : "options." + action + "_start" ),
      fields: this.fields( action , options , jobs ),
      save: ( values ) => { chosen = this.read( action , values ); },
    } );
    return answered ? chosen : null;
  },
};
