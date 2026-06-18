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
  };
}
