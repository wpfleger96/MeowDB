/* ============================================================
   views/photos.js — Photos Alpine component
   ============================================================ */

function photosView() {
  return {
    photos: [],
    isLoading: false,
    showDetail: false,
    detailPhoto: null,
    showDeleteConfirm: false,
    uploadingPhotos: false,
    photoUploadProgress: { done: 0, total: 0, errors: [] },
    isDragOver: false,
    isEditing: false,
    isCropping: false,
    _cropImg: null,
    _cropCanvas: null,
    _cropDrag: null,
    cropRect: { x: 0.1, y: 0.1, width: 0.8, height: 0.8 },

    async init() {
      await this._loadPhotos();
    },

    async _loadPhotos() {
      this.isLoading = true;
      try {
        const res = await getPhotos();
        this.photos = res.items;
      } catch (err) {
        showToast(err.message || 'Failed to load photos', 'error');
      } finally {
        this.isLoading = false;
      }
    },

    async _uploadPhotos(files) {
      if (this.uploadingPhotos) return;
      this.uploadingPhotos = true;
      this.photoUploadProgress = { done: 0, total: files.length, errors: [] };
      for (const file of files) {
        try {
          await uploadPhoto(file);
        } catch {
          this.photoUploadProgress.errors.push(file.name);
        }
        this.photoUploadProgress.done++;
      }
      this.uploadingPhotos = false;
      const total = files.length;
      const errors = this.photoUploadProgress.errors;
      const succeeded = total - errors.length;
      if (errors.length === 0) {
        showToast('Uploaded ' + total + ' photo' + (total !== 1 ? 's' : '') + '!', 'success');
      } else if (succeeded === 0) {
        showToast('All uploads failed', 'error');
      } else {
        showToast('Uploaded ' + succeeded + ' of ' + total + ' (' + errors.length + ' failed)', 'error');
      }
      await this._loadPhotos();
    },

    openDetail(photo) {
      this.detailPhoto = { ...photo };
      this.showDetail = true;
      this.showDeleteConfirm = false;
    },

    closeDetail() {
      this.showDetail = false;
      this.detailPhoto = null;
      this.showDeleteConfirm = false;
      this.isCropping = false;
      this._cropImg = null;
      this._cropDrag = null;
    },

    confirmDelete() {
      this.showDeleteConfirm = true;
    },

    async deletePhotoConfirmed() {
      if (!this.detailPhoto) return;
      if (this.authRequired && !this.authenticated) { this.showLoginModal = true; return; }
      const id = this.detailPhoto.id;
      try {
        await deletePhoto(id);
        this.photos = this.photos.filter((p) => p.id !== id);
        this.closeDetail();
        showToast('Photo deleted', 'success');
      } catch (err) {
        showToast(err.message || 'Failed to delete', 'error');
      }
    },

    async onPhotoChange(event) {
      const files = Array.from(event.target.files || []);
      event.target.value = '';
      if (files.length === 0) return;
      if (this.authRequired && !this.authenticated) {
        this.showLoginModal = true;
        return;
      }
      await this._uploadPhotos(files);
    },

    onPhotoDragOver(event) {
      event.preventDefault();
      this.isDragOver = true;
    },

    onPhotoDragLeave(event) {
      if (event.currentTarget.contains(event.relatedTarget)) return;
      this.isDragOver = false;
    },

    async onPhotoDrop(event) {
      event.preventDefault();
      this.isDragOver = false;
      if (this.authRequired && !this.authenticated) {
        this.showLoginModal = true;
        return;
      }
      const files = Array.from(event.dataTransfer?.files || []).filter(
        f => f.type.startsWith('image/')
      );
      if (files.length === 0) return;
      await this._uploadPhotos(files);
    },

    formatDate(iso) { return MeowUtils.formatDate(iso); },

    async doEdit(body) {
      if (!this.detailPhoto) return;
      const id = this.detailPhoto.id;
      try {
        await editPhoto(id, body);
        const bust = '?v=' + Date.now();
        const baseUrl = `/api/photos/${id}/image`;
        this.detailPhoto = { ...this.detailPhoto, image_url: baseUrl + bust };
        const idx = this.photos.findIndex(p => p.id === id);
        if (idx !== -1) {
          this.photos[idx] = { ...this.photos[idx], image_url: baseUrl + bust };
        }
      } catch (err) {
        showToast(err.message || 'Edit failed', 'error');
      }
    },

    async rotateCW() {
      this.isEditing = true;
      await this.doEdit({ action: 'rotate', direction: 'cw' });
      this.isEditing = false;
    },

    async rotateCCW() {
      this.isEditing = true;
      await this.doEdit({ action: 'rotate', direction: 'ccw' });
      this.isEditing = false;
    },

    async flipH() {
      this.isEditing = true;
      await this.doEdit({ action: 'flip', axis: 'horizontal' });
      this.isEditing = false;
    },

    async flipV() {
      this.isEditing = true;
      await this.doEdit({ action: 'flip', axis: 'vertical' });
      this.isEditing = false;
    },

    startCrop() {
      this.isCropping = true;
      this.cropRect = { x: 0.1, y: 0.1, width: 0.8, height: 0.8 };
      this.$nextTick(() => this._initCropCanvas());
    },

    cancelCrop() {
      this.isCropping = false;
      this._cropImg = null;
      this._cropDrag = null;
    },

    async applyCrop() {
      if (!this.isCropping) return;
      const r = this.cropRect;
      this.isCropping = false;
      this._cropImg = null;
      this._cropDrag = null;
      this.isEditing = true;
      await this.doEdit({ action: 'crop', x: r.x, y: r.y, width: r.width, height: r.height });
      this.isEditing = false;
    },

    _initCropCanvas() {
      const canvas = this.$refs.cropCanvas;
      if (!canvas || !this.detailPhoto) return;
      this._cropCanvas = canvas;
      const img = new Image();
      img.onload = () => {
        this._cropImg = img;
        this._drawCrop();
      };
      img.src = this.detailPhoto.image_url;
    },

    _drawCrop() {
      const canvas = this._cropCanvas;
      if (!canvas || !this._cropImg) return;
      const cw = canvas.width = canvas.offsetWidth;
      const ch = canvas.height = canvas.offsetHeight;
      const ctx = canvas.getContext('2d');
      const img = this._cropImg;

      const scale = Math.min(cw / img.naturalWidth, ch / img.naturalHeight);
      const dw = img.naturalWidth * scale;
      const dh = img.naturalHeight * scale;
      const dx = (cw - dw) / 2;
      const dy = (ch - dh) / 2;
      ctx.clearRect(0, 0, cw, ch);
      ctx.drawImage(img, dx, dy, dw, dh);

      const r = this.cropRect;
      const rx = dx + r.x * dw;
      const ry = dy + r.y * dh;
      const rw = r.width * dw;
      const rh = r.height * dh;

      ctx.fillStyle = 'rgba(0,0,0,0.55)';
      ctx.fillRect(0, 0, cw, ch);
      ctx.clearRect(rx, ry, rw, rh);
      ctx.drawImage(img,
        r.x * img.naturalWidth, r.y * img.naturalHeight,
        r.width * img.naturalWidth, r.height * img.naturalHeight,
        rx, ry, rw, rh
      );

      ctx.strokeStyle = '#fff';
      ctx.lineWidth = 2;
      ctx.strokeRect(rx, ry, rw, rh);

      const hs = 10;
      ctx.fillStyle = '#fff';
      for (const [hx, hy] of [[rx,ry],[rx+rw,ry],[rx,ry+rh],[rx+rw,ry+rh]]) {
        ctx.fillRect(hx - hs/2, hy - hs/2, hs, hs);
      }
    },

    _cropHitTest(cx, cy, canvas) {
      const img = this._cropImg;
      if (!img) return null;
      const cw = canvas.width, ch = canvas.height;
      const scale = Math.min(cw / img.naturalWidth, ch / img.naturalHeight);
      const dw = img.naturalWidth * scale, dh = img.naturalHeight * scale;
      const dx = (cw - dw) / 2, dy = (ch - dh) / 2;
      const r = this.cropRect;
      const rx = dx + r.x * dw, ry = dy + r.y * dh;
      const rw = r.width * dw, rh = r.height * dh;
      const hs = 14;
      const corners = [
        { name: 'tl', x: rx,    y: ry    },
        { name: 'tr', x: rx+rw, y: ry    },
        { name: 'bl', x: rx,    y: ry+rh },
        { name: 'br', x: rx+rw, y: ry+rh },
      ];
      for (const c of corners) {
        if (Math.abs(cx - c.x) <= hs && Math.abs(cy - c.y) <= hs) return { type: 'resize', handle: c.name };
      }
      if (cx >= rx && cx <= rx+rw && cy >= ry && cy <= ry+rh) return { type: 'move' };
      return { type: 'create' };
    },

    _canvasPos(e, canvas) {
      const rect = canvas.getBoundingClientRect();
      const src = e.touches ? e.touches[0] : e;
      return { x: src.clientX - rect.left, y: src.clientY - rect.top };
    },

    _fracCoords(px, py, canvas) {
      const img = this._cropImg;
      if (!img) return { fx: 0, fy: 0 };
      const cw = canvas.width, ch = canvas.height;
      const scale = Math.min(cw / img.naturalWidth, ch / img.naturalHeight);
      const dw = img.naturalWidth * scale, dh = img.naturalHeight * scale;
      const dx = (cw - dw) / 2, dy = (ch - dh) / 2;
      return {
        fx: Math.max(0, Math.min(1, (px - dx) / dw)),
        fy: Math.max(0, Math.min(1, (py - dy) / dh)),
      };
    },

    onCropPointerDown(e) {
      if (!this.isCropping) return;
      const canvas = this._cropCanvas;
      if (!canvas) return;
      e.preventDefault();
      const { x, y } = this._canvasPos(e, canvas);
      const hit = this._cropHitTest(x, y, canvas);
      this._cropDrag = { ...hit, startX: x, startY: y, origRect: { ...this.cropRect } };
    },

    onCropPointerMove(e) {
      if (!this._cropDrag || !this._cropImg) return;
      e.preventDefault();
      const canvas = this._cropCanvas;
      const { x, y } = this._canvasPos(e, canvas);
      const dx = x - this._cropDrag.startX, dy = y - this._cropDrag.startY;
      const img = this._cropImg;
      const cw = canvas.width, ch = canvas.height;
      const scale = Math.min(cw / img.naturalWidth, ch / img.naturalHeight);
      const dw = img.naturalWidth * scale, dh = img.naturalHeight * scale;
      const dfx = dx / dw, dfy = dy / dh;
      const orig = this._cropDrag.origRect;
      const MIN = 0.05;

      if (this._cropDrag.type === 'move') {
        const nx = Math.max(0, Math.min(1 - orig.width, orig.x + dfx));
        const ny = Math.max(0, Math.min(1 - orig.height, orig.y + dfy));
        this.cropRect = { ...orig, x: nx, y: ny };
      } else if (this._cropDrag.type === 'resize') {
        let { x: rx, y: ry, width: rw, height: rh } = orig;
        const h = this._cropDrag.handle;
        if (h === 'br') {
          rw = Math.max(MIN, Math.min(1 - rx, orig.width + dfx));
          rh = Math.max(MIN, Math.min(1 - ry, orig.height + dfy));
        } else if (h === 'tr') {
          const newTop = Math.max(0, Math.min(ry + rh - MIN, orig.y + dfy));
          rh = Math.max(MIN, orig.y + orig.height - newTop);
          ry = newTop;
          rw = Math.max(MIN, Math.min(1 - rx, orig.width + dfx));
        } else if (h === 'bl') {
          const newLeft = Math.max(0, Math.min(rx + rw - MIN, orig.x + dfx));
          rw = Math.max(MIN, orig.x + orig.width - newLeft);
          rx = newLeft;
          rh = Math.max(MIN, Math.min(1 - ry, orig.height + dfy));
        } else { // tl
          const newLeft = Math.max(0, Math.min(rx + rw - MIN, orig.x + dfx));
          rw = Math.max(MIN, orig.x + orig.width - newLeft);
          rx = newLeft;
          const newTop = Math.max(0, Math.min(ry + rh - MIN, orig.y + dfy));
          rh = Math.max(MIN, orig.y + orig.height - newTop);
          ry = newTop;
        }
        this.cropRect = { x: rx, y: ry, width: rw, height: rh };
      } else { // create
        const { fx: fx0, fy: fy0 } = this._fracCoords(this._cropDrag.startX, this._cropDrag.startY, canvas);
        const { fx: fx1, fy: fy1 } = this._fracCoords(x, y, canvas);
        const cx = Math.min(fx0, fx1), cy = Math.min(fy0, fy1);
        const cw2 = Math.max(MIN, Math.abs(fx1 - fx0));
        const ch2 = Math.max(MIN, Math.abs(fy1 - fy0));
        this.cropRect = { x: cx, y: cy, width: cw2, height: ch2 };
      }
      this._drawCrop();
    },

    onCropPointerUp(e) {
      this._cropDrag = null;
    },
  };
}
