import React from 'react';
import './media-type-badge.css';

export function MediaTypeBadge({kind, fallback=null}) {
  const album=kind==='douyin_album';
  if (!album&&kind!=='video'&&kind!=='mp4') return fallback;
  return <span className="media-type-badge" data-kind={album?'album':'video'}>
    <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor"
      strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {album
        ? <path d="M5.5 2h8v8M2 5h9v9H2z M3.5 12l2.5-3 1.5 1.5L9 9l2 2"/>
        : <path d="M2.5 3.5h11v9h-11z M6.5 6l3 2-3 2z"/>}
    </svg>
    {album?'图文':'视频'}
  </span>;
}
