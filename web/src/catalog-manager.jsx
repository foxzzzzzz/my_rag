import React, {useLayoutEffect, useRef, useState} from 'react';
import {splitAliases} from './management-helpers';
import './catalog.css';

const kindNames={topic:'主题',tag:'标签'};

export function CatalogManager({catalog,loaded,api,changed,disabled}) {
  const [kind,setKind]=useState('topic');
  const [query,setQuery]=useState('');
  const [editor,setEditor]=useState(null);
  const [working,setWorking]=useState(false);
  const [error,setError]=useState('');
  const [message,setMessage]=useState('');
  const dialogRef=useRef(null), nameRef=useRef(null), searchRef=useRef(null), listRef=useRef(null);
  const openerRef=useRef(null), restoreRef=useRef(null);
  const normalizedQuery=query.trim().toLocaleLowerCase();
  const items=catalog.filter(item=>item.kind===kind&&(
    !normalizedQuery||[item.name,...(item.aliases||[])].some(value=>value.toLocaleLowerCase().includes(normalizedQuery))
  ));

  useLayoutEffect(()=>{
    const dialog=dialogRef.current;
    if(editor&&!dialog.open){
      dialog.showModal();
      nameRef.current.focus();
    }
  },[editor]);

  useLayoutEffect(()=>{
    const restore=restoreRef.current;
    if(restore&&!working){
      listRef.current.scrollTop=restore.top;
      (restore.opener?.isConnected&&!restore.opener.disabled?restore.opener:searchRef.current).focus({preventScroll:true});
      restoreRef.current=null;
    }
  },[catalog,working]);

  function openEditor(event,item){
    openerRef.current=event.currentTarget;
    setError('');
    setMessage('');
    setEditor({id:item?.id,revision:item?.revision,kind:item?.kind||kind,
      name:item?.name||'',aliases:(item?.aliases||[]).join('\n')});
  }

  function closeEditor(){
    dialogRef.current.close();
    setEditor(null);
    const opener=openerRef.current;
    (opener?.isConnected&&!opener.disabled?opener:searchRef.current).focus({preventScroll:true});
  }

  async function save(event){
    event.preventDefault();
    if(!editor?.name.trim()||working||disabled)return;
    setWorking(true);
    setError('');
    const {id,revision,kind:editedKind,name,aliases}=editor;
    const body={kind:editedKind,name:name.trim(),aliases:splitAliases(aliases)};
    if(id)body.expected_revision=revision;
    try{
      await api('/classifications'+(id?'/'+encodeURIComponent(id):''),{method:'POST',body:JSON.stringify(body)});
    }catch(err){
      setError(err.message);
      setWorking(false);
      return;
    }
    if(!dialogRef.current)return;
    const restore={top:listRef.current.scrollTop,opener:openerRef.current};
    let feedback=id?'分类已保存。':`已新建${kindNames[editedKind]}。`;
    try{
      await changed();
    }catch{
      feedback='分类已保存，列表将在下次刷新时更新。';
    }
    if(!dialogRef.current)return;
    restoreRef.current=restore;
    closeEditor();
    setMessage(feedback);
    setWorking(false);
  }

  return <section className="list-page catalog-page">
    <div className="list-page-controls catalog-controls">
      <div className="page-heading">
        <h1 data-page-title tabIndex={-1}>分类</h1>
        <button type="button" className="primary" disabled={working||disabled} onClick={event=>openEditor(event)}>新建分类</button>
      </div>
      <div className="catalog-toolbar">
        <div className="catalog-kinds" role="group" aria-label="分类类型">
          {Object.entries(kindNames).map(([value,label])=><button type="button" key={value} aria-pressed={kind===value}
            onClick={()=>{setKind(value);listRef.current.scrollTop=0;}}>{label}</button>)}
        </div>
        <input ref={searchRef} type="search" aria-label="搜索名称或别名" placeholder="搜索名称或别名" value={query}
          onChange={event=>{setQuery(event.target.value);listRef.current.scrollTop=0;}}/>
      </div>
      <p className="catalog-count muted" role="status">{loaded?`${items.length} 个${kindNames[kind]}`:'正在读取分类…'}{message&&' · '+message}</p>
    </div>
    <div className="list-scroll catalog-list" ref={listRef} role="region" aria-label={kindNames[kind]+'列表'} tabIndex={0}>
      {items.length>0?<table>
        <thead><tr><th scope="col">名称</th><th scope="col">别名</th><th scope="col">操作</th></tr></thead>
        <tbody>{items.map(item=><tr key={item.id}>
          <th scope="row">{item.name}</th>
          <td>{item.aliases?.length?<ul className="catalog-aliases">{item.aliases.map(alias=><li key={alias}>{alias}</li>)}</ul>:<span className="muted" aria-label="无别名">—</span>}</td>
          <td><button type="button" className="catalog-edit" aria-label={'编辑 '+item.name}
            disabled={working||disabled} onClick={event=>openEditor(event,item)}>编辑</button></td>
        </tr>)}</tbody>
      </table>:loaded&&<p className="catalog-empty">{normalizedQuery?`没有找到匹配的${kindNames[kind]}。`:`暂无${kindNames[kind]}。`}</p>}
    </div>
    <dialog ref={dialogRef} className="catalog-editor" aria-labelledby="catalog-editor-title"
      onCancel={event=>{event.preventDefault();if(!working)closeEditor();}}>
      {editor&&<form onSubmit={save}>
        <header><h2 id="catalog-editor-title">{editor.id?'编辑分类':'新建分类'}</h2></header>
        <fieldset disabled={working||disabled}>
          <label>类型<select value={editor.kind} disabled={!!editor.id} onChange={event=>setEditor({...editor,kind:event.target.value})}>
            {Object.entries(kindNames).map(([value,label])=><option value={value} key={value}>{label}</option>)}
          </select></label>
          <label>名称<input ref={nameRef} value={editor.name} required onChange={event=>setEditor({...editor,name:event.target.value})}/></label>
          <label>别名<span className="muted">选填，可用逗号或换行分隔。</span>
            <textarea rows={4} value={editor.aliases} onChange={event=>setEditor({...editor,aliases:event.target.value})}/>
          </label>
        </fieldset>
        {editor.id&&<p className="muted catalog-editor-note">修改名称或别名后，资料会继续关联此分类。</p>}
        {error&&<p className="error" role="alert">{error}</p>}
        <footer>
          <button type="button" disabled={working} onClick={closeEditor}>取消</button>
          <button type="submit" className="primary" disabled={working||disabled||!editor.name.trim()}>{working?'保存中…':'保存'}</button>
        </footer>
      </form>}
    </dialog>
  </section>;
}
