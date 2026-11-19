import React, {useEffect, useId, useLayoutEffect, useRef, useState} from 'react';

const selects = [
  {id:'kind', label:'类型', options:[['','全部类型'], ['html','网页'], ['video','视频'], ['douyin_album','图文']]},
  {id:'review', label:'审核', options:[['','全部状态'], ['pending','待审核'], ['approve','已批准'], ['rework','返工'], ['reject','拒绝']]}
];

export function LibraryFilters({filters, filter, onResetFilters, children}) {
  const prefix = useId();
  const root = useRef(null);
  const [menu, setMenu] = useState(null);
  const openSelect = selects.find(select=>select.id===menu?.id);
  const optionId = (id, index) => `${prefix}-${id}-${index}`;

  useEffect(()=>{
    if(!openSelect) return;
    function dismiss(event) {
      const control = event.target.closest('.library-filter-trigger, .library-filter-options');
      if(!control || !root.current?.contains(control)) setMenu(null);
    }
    document.addEventListener('click', dismiss);
    return ()=>document.removeEventListener('click', dismiss);
  },[openSelect]);

  useLayoutEffect(()=>{
    if(menu?.reveal) {
      document.getElementById(optionId(menu.id, menu.index))?.scrollIntoView({block:'nearest'});
    }
  },[menu, prefix]);

  function selectOption(select, index) {
    const value = select.options[index][0];
    if(value!==filters[select.id]) filter(select.id, value);
    setMenu(null);
  }

  function onKeyDown(event, select, selectedIndex) {
    const expanded = menu?.id===select.id;
    const last = select.options.length - 1;
    if(event.key==='Tab') {
      if(expanded) selectOption(select, menu.index);
      return;
    }
    if(expanded && event.key==='Escape') {
      event.preventDefault();
      setMenu(null);
      return;
    }
    if(event.key==='F4' || (event.altKey && ['ArrowDown','ArrowUp'].includes(event.key))) {
      event.preventDefault();
      if(expanded) selectOption(select, menu.index);
      else if(event.key!=='ArrowUp') setMenu({id:select.id,index:selectedIndex});
      return;
    }
    if(event.key==='Enter' || event.key===' ') {
      event.preventDefault();
      if(expanded) selectOption(select, menu.index);
      else setMenu({id:select.id,index:selectedIndex});
      return;
    }
    let index = expanded ? menu.index : selectedIndex;
    switch(event.key) {
      case 'ArrowDown': index=Math.min(index+1,last); break;
      case 'ArrowUp': index=Math.max(index-1,0); break;
      case 'Home': index=0; break;
      case 'End': index=last; break;
      default: return;
    }
    event.preventDefault();
    if(expanded) setMenu({id:select.id,index,reveal:true});
    else selectOption(select,index);
  }

  return <div className="library-filters" ref={root}>
    <div className="toolbar">
      <label className="search"><span className="library-visually-hidden">查找</span><input value={filters.q} placeholder="搜索标题或文件名" onChange={event=>filter('q',event.target.value)}/></label>
      {selects.map(select=>{
        const id = `${prefix}-${select.id}`;
        const selectedIndex = Math.max(0, select.options.findIndex(([value])=>value===filters[select.id]));
        const expanded = menu?.id===select.id;
        return <button key={select.id} className="library-filter-trigger" type="button" role="combobox"
          aria-labelledby={`${id}-label ${id}-value`} aria-expanded={expanded}
          aria-controls={expanded ? `${id}-options` : undefined}
          aria-activedescendant={expanded ? optionId(select.id, menu.index) : undefined}
          onClick={()=>setMenu(expanded ? null : {id:select.id,index:selectedIndex})}
          onKeyDown={event=>onKeyDown(event,select,selectedIndex)}>
          <span id={`${id}-label`}>{select.label}</span>
          <span className="library-filter-value" id={`${id}-value`}>{select.options[selectedIndex][1]}</span>
          <span className="library-filter-chevron" aria-hidden="true"/>
        </button>;
      })}
      <button className="library-clear-filters" type="button" onClick={()=>{setMenu(null);onResetFilters();}}>清空筛选</button>
    </div>
    {children}
    {openSelect && <ul className="library-filter-options" data-filter={openSelect.id} id={`${prefix}-${openSelect.id}-options`}
      role="listbox" aria-labelledby={`${prefix}-${openSelect.id}-label`}>
      {openSelect.options.map(([value, label],index)=><li key={value} id={optionId(openSelect.id,index)} role="option"
        aria-selected={value===filters[openSelect.id]} data-active={menu.index===index}
        onMouseDown={event=>event.preventDefault()} onClick={()=>selectOption(openSelect,index)}>{label}</li>)}
    </ul>}
  </div>;
}
