import React from 'react';
import './media-type-badge.css';

const media = {
  video:{label:'视频',path:'M2.5 3.5h11v9h-11z M6.5 6l3 2-3 2z'},
  album:{label:'图文',path:'M5.5 2h8v8M2 5h9v9H2z M3.5 12l2.5-3 1.5 1.5L9 9l2 2'},
  web:{label:'网页',path:'M2 3h12v10H2z M2 6h12 M4.5 9h7 M4.5 11H9'}
};

export function MediaTypeBadge({kind, fallback=null, includeWeb=false, variant='solid'}) {
  const type=kind==='douyin_album' ? 'album' : ['video','mp4'].includes(kind) ? 'video' : 'web';
  if(type==='web'&&!includeWeb) return fallback;
  return <span className="media-type-badge" data-kind={type} data-variant={variant}>
    <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor"
      strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d={media[type].path}/>
    </svg>
    {media[type].label}
  </span>;
}
