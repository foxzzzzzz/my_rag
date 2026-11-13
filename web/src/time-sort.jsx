import React from 'react';

export function compareTime(a, b, direction) {
  const first = Date.parse(a);
  const second = Date.parse(b);
  if (!Number.isFinite(first)) return Number.isFinite(second) ? 1 : 0;
  if (!Number.isFinite(second)) return -1;
  return direction === 'asc' ? first - second : second - first;
}

export function TimeSortButton({label, direction, onClick, mobile = false}) {
  const ascending = direction === 'asc';
  const order = ascending ? '从早到晚' : '从晚到早';
  const nextOrder = ascending ? '从晚到早' : '从早到晚';
  return <button type="button" className={'time-sort-button'+(mobile?' time-sort-mobile':'')}
    onClick={onClick} aria-label={`按${label}排序，当前${order}，点击切换为${nextOrder}`}
    title={`当前${order}，点击切换为${nextOrder}`}>
    {label} <span aria-hidden="true">{ascending?'↑':'↓'}</span>
    {mobile&&<span aria-hidden="true">{order}</span>}
  </button>;
}
