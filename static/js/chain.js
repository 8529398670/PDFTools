// The chain screen's steps (/tools/chain): which tools run, in order, with
// which options. Each later step runs on every file the step before made
// (app/models/chains.py on the server, js/local/worker.js here). The drop zone
// below them is the same one every tool screen has (js/local.js), which asks
// Chain.steps() what to run.
//
// The steps are kept in this browser, so the chain a person built is there
// next time.
const Chain = {
  storageKey: "pdftools-chain-steps",
  maxSteps: 10,
  list: [],

  init( me ) {
    if ( me.files_enabled === false ) return;
    this.list = this.saved();
    const picker = Dom.get( "chain-add-tool" );
    Dom.swap( picker , ...ToolOptions.chainable.map( ( action ) => Dom.el( "option" , { attrs: { value: action } , text: ToolOptions.name( action ) } ) ) );
    Dom.onPress( Dom.get( "chain-add" ) , () => this.add( picker.value ) );
    this.render();
  },

  saved() {
    try {
      const raw = JSON.parse( window.localStorage.getItem( this.storageKey ) || "[]" );
      if ( Array.isArray( raw ) ) {
        return raw.filter( ( step ) => step && ToolOptions.chainable.includes( step.action ) ).slice( 0 , this.maxSteps )
          .map( ( step ) => ( { action: step.action , options: ToolOptions.merged( step.action , step.options ) } ) );
      }
    } catch ( error ) { /* nothing saved, or private mode */ }
    return [];
  },

  save() {
    try { window.localStorage.setItem( this.storageKey , JSON.stringify( this.list ) ); } catch ( error ) { /* private mode */ }
  },

  // What the drop zone runs: a copy, so a change while it runs is not seen.
  steps() {
    return this.list.map( ( step ) => ( { action: step.action , options: Object.assign( {} , step.options ) } ) );
  },

  async edit( index , adding ) {
    const step = adding || this.list[ index ];
    let chosen = null;
    const answered = await Dom.form( {
      title: I18n.get( "chain.edit_title" ).replace( "{number}" , index + 1 ).replace( "{tool}" , ToolOptions.name( step.action ) ),
      submit: adding ? I18n.get( "chain.add" ) : I18n.get( "ui.save" ),
      fields: ToolOptions.fields( step.action , step.options ),
      save: ( values ) => { chosen = ToolOptions.read( step.action , values ); },
    } );
    if ( !answered ) return false;
    step.options = chosen;
    if ( adding ) this.list.push( step );
    this.save();
    this.render();
    return true;
  },

  add( action ) {
    if ( this.list.length >= this.maxSteps ) {
      Dom.toast( I18n.get( "chain.too_many" ).replace( "{count}" , this.maxSteps ) , "error" );
      return;
    }
    this.edit( this.list.length , { action: action , options: ToolOptions.merged( action ) } );
  },

  move( index , by ) {
    const to = index + by;
    if ( to < 0 || to >= this.list.length ) return;
    [ this.list[ index ] , this.list[ to ] ] = [ this.list[ to ] , this.list[ index ] ];
    this.save();
    this.render();
  },

  remove( index ) {
    this.list.splice( index , 1 );
    this.save();
    this.render();
  },

  iconButton( icon , label , run , disabled ) {
    return Dom.el( "button" , {
      class: "btn btn-sm btn-outline-secondary",
      attrs: { type: "button" , "aria-label": label , title: label , ...( disabled ? { disabled: "" } : {} ) },
      children: [ Dom.el( "i" , { class: "bi " + icon , attrs: { "aria-hidden": "true" } } ) ],
      on: { click: run },
    } );
  },

  render() {
    const holder = Dom.get( "chain-steps" );
    const rows = this.list.map( ( step , index ) => Dom.el( "li" , {
      class: "list-group-item d-flex flex-wrap align-items-center gap-2",
      children: [
        Dom.el( "span" , { class: "badge text-bg-secondary" , text: String( index + 1 ) } ),
        Dom.el( "span" , { class: "flex-grow-1 text-break" , text: ToolOptions.summary( step.action , step.options ) } ),
        Dom.el( "div" , { class: "btn-group" , attrs: { role: "group" } , children: [
          this.iconButton( "bi-arrow-up" , I18n.get( "chain.up" ) , () => this.move( index , -1 ) , index === 0 ),
          this.iconButton( "bi-arrow-down" , I18n.get( "chain.down" ) , () => this.move( index , 1 ) , index === this.list.length - 1 ),
          this.iconButton( "bi-sliders" , I18n.get( "chain.edit" ) , () => this.edit( index ) ),
          this.iconButton( "bi-trash" , I18n.get( "chain.remove" ) , () => this.remove( index ) ),
        ] } ),
      ],
    } ) );
    Dom.swap( holder , ...rows );
    Dom.show( holder , rows.length > 0 );
    Dom.show( Dom.get( "chain-empty" ) , rows.length === 0 );
    Dom.get( "chain-add" ).disabled = this.list.length >= this.maxSteps;
    if ( typeof Local !== "undefined" && Local.paintEngine ) Local.paintEngine();
  },
};
