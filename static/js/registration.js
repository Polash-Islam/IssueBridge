(() => {
  const division = document.getElementById('id_division');
  const role = document.getElementById('id_role');
  const data = document.getElementById('registration-role-options');
  if (!division || !role || !data) return;

  const roles = JSON.parse(data.textContent);
  function updateRoles(selected = '') {
    const matching = roles.filter(item => String(item.division_id) === division.value);
    const placeholder = !division.value
      ? 'Select a division first'
      : matching.length ? 'Select a role' : 'No roles available for this division';
    role.replaceChildren(new Option(placeholder, ''));
    matching.forEach(item => role.add(new Option(item.name, item.pk)));
    role.value = matching.some(item => String(item.pk) === String(selected)) ? selected : '';
    role.disabled = matching.length === 0;
  }

  division.addEventListener('change', () => updateRoles());
  updateRoles(role.value);
})();
