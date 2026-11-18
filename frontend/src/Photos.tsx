import { useEffect, useRef, useState } from 'react';

export const photoTypes = 'image/jpeg,image/png,image/webp';
export type Photo = { id: string; original_name: string; work_order_id: string | null };

export async function uploadPhoto(token: string, requestId: string, file: File, orderId?: string) {
  if (file.size > 8 * 1024 * 1024) throw new Error('Photos must be 8 MB or smaller.');
  const query = new URLSearchParams({ name: file.name });
  if (orderId) query.set('work_order_id', orderId);
  const response = await fetch(`/api/requests/${requestId}/photos?${query}`, {
    method: 'POST', headers: { Authorization: `Bearer ${token}` }, body: file,
  });
  if (!response.ok) {
    const result = await response.json().catch(() => null);
    throw new Error(response.status === 401 ? 'Your session expired. Sign in again.'
      : typeof result?.detail === 'string' ? result.detail : 'Unable to upload photo.');
  }
}

function PhotoTile({ token, path, photo }: { token: string; path: string; photo: Photo }) {
  const [thumbnail, setThumbnail] = useState('');
  const [full, setFull] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const dialog = useRef<HTMLDialogElement>(null);
  const requestFull = useRef<AbortController>(null);

  useEffect(() => {
    const controller = new AbortController();
    let url = '';
    fetch(`${path}?thumbnail=true`, {
      headers: { Authorization: `Bearer ${token}` }, signal: controller.signal,
    }).then(response => {
      if (!response.ok) throw new Error();
      return response.blob();
    }).then(blob => {
      if (controller.signal.aborted) return;
      url = URL.createObjectURL(blob);
      setThumbnail(url);
    }).catch(() => { if (!controller.signal.aborted) setError('Preview unavailable.'); });
    return () => { controller.abort(); if (url) URL.revokeObjectURL(url); };
  }, [path, token]);

  useEffect(() => {
    if (!full) return;
    const current = dialog.current;
    current?.showModal();
    return () => { current?.close(); URL.revokeObjectURL(full); };
  }, [full]);

  useEffect(() => {
    const controller = new AbortController();
    requestFull.current = controller;
    return () => controller.abort();
  }, [path, token]);

  async function view() {
    const signal = requestFull.current?.signal;
    setError(''); setLoading(true);
    try {
      const response = await fetch(path, { headers: { Authorization: `Bearer ${token}` }, signal });
      if (!response.ok) throw new Error();
      const blob = await response.blob();
      if (!signal?.aborted) setFull(URL.createObjectURL(blob));
    } catch { if (!signal?.aborted) setError('Photo unavailable.'); }
    finally { if (!signal?.aborted) setLoading(false); }
  }

  return <figure className="photo-tile">
    <button type="button" className="secondary" disabled={loading} onClick={() => void view()} aria-label={`View ${photo.original_name}`}>
      {thumbnail ? <img src={thumbnail} alt="" /> : 'View photo'}
    </button>
    <figcaption>{photo.work_order_id ? 'Repair photo' : 'Issue photo'} · {photo.original_name}</figcaption>
    {error && <small role="status">{error}</small>}
    {full && <dialog ref={dialog} className="photo-dialog" aria-label={photo.original_name} onClose={() => setFull('')}>
      <button type="button" className="secondary photo-close" onClick={() => dialog.current?.close()}>
        Close photo
      </button>
      <img src={full} alt={photo.original_name} />
    </dialog>}
  </figure>;
}

export function PhotoGallery({ token, requestId, photos }: { token: string; requestId: string; photos: Photo[] }) {
  if (!photos.length) return null;
  return <section aria-label="Request photos">
    <h3>Photos</h3>
    <div className="photo-grid">{photos.map(photo => <PhotoTile key={photo.id} token={token}
      photo={photo} path={`/api/requests/${requestId}/photos/${photo.id}`} />)}</div>
  </section>;
}
