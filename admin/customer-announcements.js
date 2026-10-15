/* Admin-only editor for messages displayed in authenticated customer spaces. */
(() => {
  'use strict';
  const endpoint = '/api/admin/customer-announcements';
  const $ = id => document.getElementById(id);
  const list = $('announcementAdminList');
  const state = $('announcementAdminStatus');
  const add = $('announcementAdd');
  const input = $('announcementNewMessage');
  const enabled = $('announcementNewEnabled');
  if (!list || !state || !add || !input || !enabled) return;

  let busy = false;
  const status = (message, error = false) => {
    state.textContent = message;
    state.classList.toggle('error', error);
  };
  const make = (tag, cls = '', label = '') => {
    const element = document.createElement(tag);
    if (cls) element.className = cls;
    if (label) element.textContent = label;
    return element;
  };
  async function request(payload) {
    const init = {
      credentials: 'same-origin',
      cache: 'no-store',
      headers: {'Accept': 'application/json'}
    };
    if (payload) {
      init.method = 'POST';
      init.headers['Content-Type'] = 'application/json';
      init.body = JSON.stringify(payload);
    }
    const response = await fetch(endpoint, init);
    const result = await response.json();
    if (!response.ok || result.ok !== true || !Array.isArray(result.items)) {
      throw new Error(result.error || 'Enregistrement impossible.');
    }
    return result.items;
  }
  const guarded = async operation => {
    if (busy) return;
    busy = true;
    add.disabled = true;
    status('Enregistrement…');
    try {
      const items = await operation();
      render(items);
      status('Informations enregistrées et publiées.');
    } catch (error) {
      status(error.message || 'Opération impossible.', true);
    } finally {
      busy = false;
      add.disabled = false;
    }
  };

  function render(items) {
    list.replaceChildren();
    if (!items.length) {
      list.append(make('p', 'hint', 'Aucune information. Publiez votre premier message.'));
      return;
    }
    for (const item of items) {
      const card = make('article', 'announcement-admin-card');
      const heading = make('div', 'announcement-admin-heading');
      heading.append(make('strong', '', 'Information n°' + item.id));
      const switchLabel = make('label', 'announcement-active');
      const toggle = make('input');
      toggle.type = 'checkbox';
      toggle.checked = item.enabled === true;
      switchLabel.append(toggle, document.createTextNode(' Afficher aux clients'));
      heading.append(switchLabel);
      card.append(heading);

      const textLabel = make('label');
      textLabel.textContent = 'Message diffusé';
      const editor = make('textarea');
      editor.value = item.message;
      editor.maxLength = 400;
      editor.rows = 3;
      textLabel.append(editor);
      card.append(textLabel);

      const actions = make('div', 'button-row');
      const save = make('button', '', 'Enregistrer');
      save.type = 'button';
      const remove = make('button', 'danger', 'Supprimer');
      remove.type = 'button';
      save.addEventListener('click', () => guarded(
        () => request({action: 'update', id: item.id, message: editor.value, enabled: toggle.checked})
      ));
      remove.addEventListener('click', () => {
        if (window.confirm('Supprimer définitivement cette information ?')) {
          guarded(() => request({action: 'delete', id: item.id}));
        }
      });
      actions.append(save, remove);
      card.append(actions);
      list.append(card);
    }
  }

  add.addEventListener('click', () => guarded(async () => {
    const items = await request({action: 'create', message: input.value, enabled: enabled.checked});
    input.value = '';
    return items;
  }));
  request().then(items => {
    render(items);
    status('Les informations actives sont visibles dans les espaces clients.');
  }).catch(error => status(error.message || 'Chargement impossible.', true));
})();
