document.addEventListener('DOMContentLoaded', () => {
  const search = document.getElementById('assetSearch');
  const cards = Array.from(document.querySelectorAll('.asset-card-wrap'));
  const empty = document.getElementById('noSearchResults');
  if (search) {
    search.addEventListener('input', () => {
      const term = search.value.trim().toLowerCase();
      let shown = 0;
      cards.forEach(card => {
        const match = card.dataset.search.includes(term);
        card.classList.toggle('d-none', !match);
        if (match) shown++;
      });
      if (empty) empty.classList.toggle('d-none', shown !== 0);
    });
  }
  document.querySelectorAll('form[data-confirm]').forEach(form => {
    form.addEventListener('submit', event => {
      if (!window.confirm(form.dataset.confirm || 'Are you sure?')) event.preventDefault();
    });
  });
  const dateInput = document.getElementById('booking_date');
  if (dateInput && !dateInput.min) {
    const now = new Date();
    const localDate = new Date(now.getTime() - now.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
    dateInput.min = localDate;
  }
});
