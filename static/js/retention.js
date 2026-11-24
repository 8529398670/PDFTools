// How long files are kept: your own choice (a card on Account), and the policy
// every admin can set for everyone (Admin > Retention). The rules are on the
// server, in app/models/retention.py; this only shows and sends them.
const Retention = {
  me: null,

  async init( me ) {
    this.me = me;
    if ( me.files_enabled === false ) return;
    Dom.show( Dom.get( "my-retention-panel" ) , true );
    Dom.onSubmit( Dom.get( "my-retention-form" ) , this.onSaveMine.bind( this ) );
    const loading = [ this.loadMine() ];
    if ( me.role === "admin" ) {
      Dom.show( Dom.get( "retention-panel" ) , true );
      Dom.onSubmit( Dom.get( "retention-policy-form" ) , this.onSavePolicy.bind( this ) );
      loading.push( this.loadPolicy() );
    }
    await Promise.all( loading );
  },

  // "30 days", or "until deleted" for 0.
  days( count ) {
    if ( count === 1 ) return I18n.get( "retention.day" );
    return count > 0 ? I18n.get( "retention.days" ).replace( "{count}" , count ) : I18n.get( "retention.forever" );
  },

  // A blank field follows the default, so it sends null.
  read( input ) {
    return input.value.trim() === "" ? null : Number( input.value );
  },

  showMine( mine ) {
    const policy = mine.policy;
    Dom.get( "my-import-days" ).value = mine.import_days === null ? "" : mine.import_days;
    Dom.get( "my-output-days" ).value = mine.output_days === null ? "" : mine.output_days;
    Dom.get( "my-import-days" ).placeholder = String( policy.import_days );
    Dom.get( "my-output-days" ).placeholder = String( policy.output_days );
    const limit = policy.max_days > 0 ? I18n.get( "retention.limit" ).replace( "{days}" , this.days( policy.max_days ) ) : I18n.get( "retention.no_limit" );
    Dom.text( Dom.get( "my-retention-text" ) , I18n.get( "retention.mine_now" )
      .replace( "{imports}" , this.days( mine.effective_import_days ) )
      .replace( "{outputs}" , this.days( mine.effective_output_days ) ) + " " + limit );
    this.current = mine;
  },

  async loadMine() {
    this.showMine( await Api.myRetention() );
  },

  async onSaveMine( event ) {
    event.preventDefault();
    const before = this.current;
    const values = { import_days: this.read( Dom.get( "my-import-days" ) ) , output_days: this.read( Dom.get( "my-output-days" ) ) };
    try {
      this.showMine( await Api.setMyRetention( values ) );
    } catch ( error ) {
      App.showError( error.message );
      return;
    }
    Undo.saved( Dom.get( "my-retention-form" ) );
    Undo.record( {
      label: I18n.get( "undo.retention" ),
      undo: async () => this.showMine( await Api.setMyRetention( { import_days: before.import_days , output_days: before.output_days } ) ),
      redo: async () => this.showMine( await Api.setMyRetention( values ) ),
    } );
    Dom.toast( I18n.get( "ui.saved" ) , "ok" );
  },

  showPolicy( policy ) {
    Dom.get( "policy-import-days" ).value = policy.import_days;
    Dom.get( "policy-output-days" ).value = policy.output_days;
    Dom.get( "policy-max-days" ).value = policy.max_days;
    Dom.text( Dom.get( "policy-updated" ) , policy.updated_at
      ? I18n.get( "retention.updated" ).replace( "{when}" , new Date( policy.updated_at ).toLocaleString() )
      : "" );
    this.policy = policy;
  },

  async loadPolicy() {
    this.showPolicy( await Api.retentionPolicy() );
  },

  async onSavePolicy( event ) {
    event.preventDefault();
    const before = this.policy;
    const values = {
      import_days: Number( Dom.get( "policy-import-days" ).value ),
      output_days: Number( Dom.get( "policy-output-days" ).value ),
      max_days: Number( Dom.get( "policy-max-days" ).value ),
    };
    try {
      this.showPolicy( await Api.setRetentionPolicy( values ) );
    } catch ( error ) {
      App.showError( error.message );
      return;
    }
    Undo.saved( Dom.get( "retention-policy-form" ) );
    const back = { import_days: before.import_days , output_days: before.output_days , max_days: before.max_days };
    Undo.record( {
      label: I18n.get( "undo.retention_policy" ),
      undo: async () => this.showPolicy( await Api.setRetentionPolicy( back ) ),
      redo: async () => this.showPolicy( await Api.setRetentionPolicy( values ) ),
    } );
    Dom.toast( I18n.get( "ui.saved" ) , "ok" );
    await this.loadMine();
    window.dispatchEvent( new Event( "work:files" ) );
  },
};
