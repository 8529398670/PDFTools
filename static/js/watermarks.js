// Remove watermarks' findings, as a list to pick from: under a finished run
// on its tool screen (js/local.js) and on Runs (js/runs.js).
//
// A run's result (app/actions/remove_watermarks.py, or its browser twin)
// holds findings: { id , detector , description , pages , page_summary ,
// confidence , actionable , evidence: [ { label , weight } ] , applied? }.
// Each is a row with a box, ticked to start with when it is at least as sure
// as the run asked for and can be removed at all. Findings much less sure
// than that are folded under "N less likely". "Remove selected" hands the
// ticked ids to onRemove, which starts a remove run with them as picked.
//
// The list is drawn again whenever its holder is, so what is ticked lives in
// state (kept by the caller, one per run), not in the boxes.
const Watermarks = {
  // Below this, a finding is folded away until asked for.
  unlikelyBelow: 0.3,

  // A fresh state for result: the boxes ticked to start with.
  state( result ) {
    const threshold = result && typeof result.min_confidence === "number" ? result.min_confidence : 0.5;
    const ticked = ( result && result.findings || [] ).filter( ( finding ) => finding.actionable && (
      result.mode === "remove" ? finding.applied : finding.confidence >= threshold ) );
    return { picked: new Set( ticked.map( ( finding ) => finding.id ) ) , unlikely: false };
  },

  // Words for a finished run's line: removed n, or found n.
  note( result , prefix ) {
    if ( !result || !Array.isArray( result.findings ) ) return "";
    if ( result.mode === "check" ) {
      return I18n.get( prefix + ".wm_found" ).replace( "{count}" , result.findings.filter( ( finding ) => finding.actionable ).length );
    }
    return result.removed
      ? I18n.get( prefix + ".wm_removed" ).replace( "{count}" , result.removed )
      : I18n.get( prefix + ".wm_none" );
  },

  // The list for result, with state as Watermarks.state made it.
  // onRemove( ids ) starts the remove run; null leaves the button out.
  panel( result , state , onRemove ) {
    const findings = result && result.findings || [];
    if ( findings.length === 0 ) {
      return Dom.el( "p" , { class: "text-body-secondary small mb-0" , text: I18n.get( "watermarks.nothing" ) } );
    }
    const likely = findings.filter( ( finding ) => finding.confidence >= this.unlikelyBelow || !finding.actionable );
    const unlikely = findings.filter( ( finding ) => finding.confidence < this.unlikelyBelow && finding.actionable );
    const button = onRemove ? Dom.el( "button" , {
      class: "btn btn-sm btn-primary",
      attrs: { type: "button" },
      children: [
        Dom.el( "i" , { class: "bi bi-eraser me-1" , attrs: { "aria-hidden": "true" } } ),
        Dom.el( "span" ),
      ],
    } ) : null;
    const paintButton = () => {
      if ( !button ) return;
      Dom.text( button.lastChild , I18n.get( "watermarks.remove_selected" ).replace( "{count}" , state.picked.size ) );
      button.disabled = state.picked.size === 0;
    };
    if ( button ) {
      button.addEventListener( "click" , Dom.press( button , async () => {
        if ( state.picked.size === 0 ) {
          Dom.toast( I18n.get( "watermarks.none_selected" ) , "error" );
          return;
        }
        await onRemove( [ ...state.picked ] );
      } ) );
    }
    const rows = ( list ) => list.map( ( finding ) => this.row( finding , state , paintButton ) );
    const children = [
      Dom.el( "h4" , { class: "h6 mb-2" , text: I18n.get( "watermarks.heading" ) } ),
      Dom.el( "ul" , { class: "list-group mb-2" , children: rows( likely ) } ),
    ];
    if ( unlikely.length ) {
      const folded = Dom.el( "ul" , { class: "list-group mb-2" , children: rows( unlikely ) } );
      const details = Dom.el( "details" , { class: "mb-2" , children: [
        Dom.el( "summary" , { class: "small text-body-secondary" , text: I18n.get( "watermarks.unlikely" ).replace( "{count}" , unlikely.length ) } ),
        folded,
      ] } );
      details.open = state.unlikely;
      details.addEventListener( "toggle" , () => { state.unlikely = details.open; } );
      children.push( details );
    }
    if ( result.more ) children.push( Dom.el( "p" , { class: "small text-body-secondary mb-2" , text: I18n.get( "watermarks.more" ).replace( "{count}" , result.more ) } ) );
    if ( button ) children.push( button );
    paintButton();
    return Dom.el( "div" , { class: "mt-2" , children } );
  },

  // One finding: its box, how sure, what it is, on which pages, and why.
  row( finding , state , changed ) {
    const id = "wm-" + finding.id + "-" + Math.random().toString( 36 ).slice( 2 , 7 );
    const percent = Math.round( finding.confidence * 100 );
    const tone = finding.confidence >= 0.8 ? "danger" : finding.confidence >= 0.5 ? "warning" : "secondary";
    const head = [];
    if ( finding.actionable ) {
      const box = Dom.el( "input" , { class: "form-check-input mt-1 flex-shrink-0" , attrs: { type: "checkbox" , id: id } } );
      box.checked = state.picked.has( finding.id );
      box.addEventListener( "change" , () => {
        if ( box.checked ) state.picked.add( finding.id );
        else state.picked.delete( finding.id );
        changed();
      } );
      head.push( box );
    } else {
      head.push( Dom.el( "i" , { class: "bi bi-info-circle text-body-secondary mt-1 flex-shrink-0" , attrs: { "aria-hidden": "true" } } ) );
    }
    const badges = [ Dom.badge( finding.actionable ? I18n.get( "watermarks.sure" ).replace( "{percent}" , percent ) : I18n.get( "watermarks.info_only" ) ,
      finding.actionable ? tone : "light" ) ];
    if ( finding.applied ) badges.push( Dom.badge( I18n.get( "watermarks.removed" ) , "success" ) );
    head.push( Dom.el( "label" , {
      class: "flex-grow-1 text-break",
      attrs: finding.actionable ? { for: id } : {},
      children: [
        Dom.el( "span" , { class: "d-block" , text: finding.description } ),
        Dom.el( "span" , { class: "d-flex flex-wrap gap-1 align-items-center small text-body-secondary mt-1" , children: [
          ...badges,
          Dom.el( "span" , { text: I18n.get( "watermarks.pages" ).replace( "{pages}" , finding.page_summary ) } ),
        ] } ),
      ],
    } ) );
    const why = ( finding.evidence || [] ).filter( ( item ) => item.label );
    const evidence = why.length ? Dom.el( "details" , { class: "small mt-1 ms-4" , children: [
      Dom.el( "summary" , { class: "text-body-secondary" , text: I18n.get( "watermarks.evidence" ) } ),
      Dom.el( "ul" , { class: "list-unstyled mb-0 ps-2" , children: why.map( ( item ) => Dom.el( "li" , {
        class: item.weight > 0 ? "" : item.weight < 0 ? "text-body-secondary" : "",
        text: ( item.weight > 0 ? "+ " : item.weight < 0 ? "− " : "" ) + item.label,
      } ) ) } ),
    ] } ) : null;
    return Dom.el( "li" , { class: "list-group-item" , children: [
      Dom.el( "div" , { class: "d-flex gap-2 align-items-start" , children: head } ),
      ...( evidence ? [ evidence ] : [] ),
    ] } );
  },
};
