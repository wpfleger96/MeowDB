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
      if (this.$root.authRequired && !this.$root.authenticated) { this.$root.showLoginModal = true; return; }
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
      const file = event.target.files?.[0];
      if (!file) return;
      event.target.value = '';
      if (this.$root.authRequired && !this.$root.authenticated) {
        this.$root.showLoginModal = true;
        return;
      }
      try {
        await uploadPhoto(file);
        showToast('Photo uploaded!', 'success');
        await this._loadPhotos();
      } catch (err) {
        showToast(err.message || 'Photo upload failed', 'error');
      }
    },

    formatDate(iso) { return MeowUtils.formatDate(iso); },
  };
}
