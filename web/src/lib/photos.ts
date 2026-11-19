/** A photo ready to send to the server: JPEG, base64 without the data: prefix. */
export type PhotoUpload = { data: string; type: 'image/jpeg' };

/**
 * Shrink a photo from the camera or the library before uploading.
 *
 * Phone photos are often 4 to 12 MB; for reading a cookbook page or a cover, the long side
 * needs no more than about 2000 pixels. Drawing into a canvas also turns HEIC from iPhones
 * into JPEG and applies the camera's rotation.
 */
export async function preparePhoto(file: File, maxSide = 2000, quality = 0.85): Promise<PhotoUpload> {
  const image = await loadImage(file);
  const scale = Math.min(1, maxSide / Math.max(image.width, image.height));
  const width = Math.max(1, Math.round(image.width * scale));
  const height = Math.max(1, Math.round(image.height * scale));
  const canvas = document.createElement('canvas');
  canvas.width = width;
  canvas.height = height;
  const context = canvas.getContext('2d');
  if (!context) throw new Error('Das Foto konnte nicht verarbeitet werden.');
  context.drawImage(image.source, 0, 0, width, height);
  if ('close' in image.source) image.source.close();
  const dataUrl = canvas.toDataURL('image/jpeg', quality);
  return { data: dataUrl.slice(dataUrl.indexOf(',') + 1), type: 'image/jpeg' };
}

type Loaded = { source: ImageBitmap | HTMLImageElement; width: number; height: number };

async function loadImage(file: File): Promise<Loaded> {
  if ('createImageBitmap' in window) {
    try {
      const bitmap = await createImageBitmap(file, { imageOrientation: 'from-image' });
      return { source: bitmap, width: bitmap.width, height: bitmap.height };
    } catch {
      // Older Safari: fall back to an <img>, which also applies the rotation.
    }
  }
  const url = URL.createObjectURL(file);
  try {
    const img = new Image();
    img.src = url;
    await img.decode();
    return { source: img, width: img.naturalWidth, height: img.naturalHeight };
  } catch {
    throw new Error('Dieses Bild kann die App nicht öffnen. Versuch es mit einem anderen Foto.');
  } finally {
    URL.revokeObjectURL(url);
  }
}
