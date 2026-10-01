(() => {
  const division = document.getElementById('id_division');
  const designation = document.getElementById('id_designation');
  const data = document.getElementById('registration-designation-roles');
  if (!division || !designation || !data) return;

  const roles = JSON.parse(data.textContent);
  function updateDesignations(selected = '') {
    const matching = roles.filter(role => (
      role.division_id === null || String(role.division_id) === division.value
    ));
    const placeholder = !division.value
      ? 'Select a division first'
      : matching.length ? 'Select a designation' : 'No roles available for this division';
    designation.replaceChildren(new Option(placeholder, ''));
    matching.forEach(role => designation.add(new Option(role.name, role.name)));
    designation.value = matching.some(role => role.name === selected) ? selected : '';
    designation.disabled = matching.length === 0;
  }

  division.addEventListener('change', () => updateDesignations());
  updateDesignations(designation.value);
})();
