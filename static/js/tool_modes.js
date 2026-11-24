// Account > Where your tools run: the account's default run mode and an
// override per tool, saved on the account (POST /api/account/tool-modes) so
// they follow the person to every device. See js/tools.js for how a tool
// reads them and app/models/tool_modes.py for what is stored.
//
// The default is three buttons (Automatic, This device, The server). Each tool
// has a select: "Use my default" (nothing stored) or one of the three.
// Choices a tool's engines rule out are disabled. Saving sends the whole set.
const ToolModes = {
  draft: {},

  init( me ) {
    Dom.show( Dom.get( "tool-modes-panel" ) , true );
    this.draft = Object.assign( {} , me.tool_modes || {} );
    this.paint();
    Dom.onSubmit( Dom.get( "tool-modes-form" ) , async ( event ) => {
      event.preventDefault();
      await this.save( this.draft );
    } );
    Dom.onPress( Dom.get( "tool-modes-reset" ) , async () => {
      this.draft = {};
      this.paint();
      await this.save( {} );
    } );
  },

  async save( modes ) {
    const reply = await Api.setToolModes( modes );
    this.draft = Object.assign( {} , reply.tool_modes );
    Tools.changed( Object.assign( {} , reply.tool_modes ) );
    this.paint();
    Dom.toast( I18n.get( "tool_modes.saved" ) , "ok" );
  },

  defaultMode() {
    return Tools.modes.includes( this.draft[ "*" ] ) ? this.draft[ "*" ] : "auto";
  },

  paint() {
    this.paintDefault();
    this.paintRows();
  },

  paintDefault() {
    const group = Dom.get( "tool-modes-default" );
    Dom.clear( group );
    const current = this.defaultMode();
    Tools.modes.forEach( ( mode ) => {
      const id = "tool-modes-default-" + mode;
      const input = Dom.el( "input" , { class: "btn-check" , attrs: { type: "radio" , name: "tool-modes-default" , id: id , value: mode , autocomplete: "off" } } );
      input.checked = mode === current;
      input.addEventListener( "change" , () => {
        if ( mode === "auto" ) delete this.draft[ "*" ];
        else this.draft[ "*" ] = mode;
        this.paint();
      } );
      group.appendChild( input );
      group.appendChild( Dom.el( "label" , { class: "btn btn-outline-primary" , attrs: { for: id } , text: Tools.modeLabel( mode ) } ) );
    } );
    Dom.text( Dom.get( "tool-modes-default-help" ) , this.deviceHelp( current ) );
  },

  // What the default means on the device in hand, worded as the tool screens word it.
  deviceHelp( mode ) {
    const device = Local.device();
    if ( !device.supported ) return I18n.get( "local.unsupported" );
    if ( mode !== "auto" ) return "";
    const memory = device.memory === null ? "" : I18n.get( "local.memory" ).replace( "{gb}" , device.memory );
    return I18n.get( device.capable ? "local.auto_device" : "local.auto_server" ).replace( "{cores}" , device.cores ).replace( "{memory}" , memory );
  },

  paintRows() {
    const body = Dom.get( "tool-modes-rows" );
    Dom.clear( body );
    const inherit = I18n.get( "tool_modes.inherit" ).replace( "{mode}" , Tools.modeLabel( this.defaultMode() ) );
    let set = 0;
    Tools.all().forEach( ( tool ) => {
      const engines = tool.engines || Tools.engines;
      const select = Dom.el( "select" , {
        class: "form-select form-select-sm",
        attrs: { "aria-label": Tools.title( tool.id ) },
        children: [ Dom.el( "option" , { attrs: { value: "" } , text: inherit } ) ].concat( Tools.modes.map( ( mode ) => {
          const option = Dom.el( "option" , { attrs: { value: mode } , text: Tools.modeLabel( mode ) } );
          option.disabled = mode !== "auto" && !engines.includes( mode );
          return option;
        } ) ),
      } );
      select.value = this.draft[ tool.id ] || "";
      if ( this.draft[ tool.id ] ) set += 1;
      select.addEventListener( "change" , () => {
        if ( select.value === "" ) delete this.draft[ tool.id ];
        else this.draft[ tool.id ] = select.value;
        this.paintCount();
      } );
      const name = Dom.el( "td" , { children: [ Dom.el( "span" , { class: "me-2" , text: Tools.title( tool.id ) } ) ] } );
      if ( !tool.ready ) name.appendChild( Dom.badge( I18n.get( "tools.todo" ) , "warning" ) );
      body.appendChild( Dom.el( "tr" , {
        children: [
          name,
          Dom.el( "td" , { class: "d-none d-md-table-cell text-body-secondary" , text: I18n.get( "tools.sections." + tool.section ) } ),
          Dom.el( "td" , { class: "tool-mode-cell" , children: [ select ] } ),
        ],
      } ) );
    } );
    this.paintCount( set );
  },

  paintCount( known ) {
    const set = known !== undefined ? known : Object.keys( this.draft ).filter( ( key ) => key !== "*" ).length;
    const badge = Dom.get( "tool-modes-overrides-count" );
    Dom.text( badge , I18n.get( "tool_modes.overrides_count" ).replace( "{count}" , set ) );
    Dom.show( badge , set > 0 );
  },
};
