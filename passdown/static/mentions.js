// Lightweight @mention / #hashtag autocomplete for plain <textarea>
// elements. Typing "@" suggests team member names AND tool/entity names
// combined (an @mention can reference either — e.g. "@Alan" or "@CR1" —
// distinguished server-side when rendering bubbles, not here); typing
// "#" suggests hashtags previously used in other entries (see
// db.get_hashtags() — there's no manual tag list, tags are just learned
// from usage). Arrow keys, Enter/Tab, Escape, and mouse click all work;
// selecting an item replaces the partial "@foo" / "#foo" token at the
// cursor with the full name/tag plus a trailing space.
function initMentionAutocomplete(textarea, names, tags) {
    if (!textarea) return;

    var dropdown = document.createElement('div');
    dropdown.className = 'mention-dropdown';
    dropdown.style.display = 'none';
    document.body.appendChild(dropdown);

    var activeIndex = -1;
    var currentMatches = [];
    var triggerStart = -1; // index in textarea.value where @ or # starts

    function hide() {
        dropdown.style.display = 'none';
        activeIndex = -1;
        currentMatches = [];
        triggerStart = -1;
    }

    function position() {
        var rect = textarea.getBoundingClientRect();
        dropdown.style.left = (rect.left + window.scrollX) + 'px';
        dropdown.style.top = (rect.bottom + window.scrollY + 4) + 'px';
        dropdown.style.width = Math.min(rect.width, 260) + 'px';
    }

    function render() {
        dropdown.innerHTML = '';
        currentMatches.forEach(function (item, idx) {
            var opt = document.createElement('div');
            opt.className = 'mention-option' + (idx === activeIndex ? ' mention-option-active' : '');
            opt.textContent = item;
            opt.addEventListener('mousedown', function (e) {
                e.preventDefault(); // don't let the textarea lose focus before we act
                select(idx);
            });
            dropdown.appendChild(opt);
        });
        dropdown.style.display = currentMatches.length ? 'block' : 'none';
    }

    function select(idx) {
        var item = currentMatches[idx];
        if (item === undefined || triggerStart === -1) { hide(); return; }
        var value = textarea.value;
        var trigger = value[triggerStart];
        var cursor = textarea.selectionStart;
        var before = value.slice(0, triggerStart);
        var after = value.slice(cursor);
        var inserted = trigger + item + ' ';
        textarea.value = before + inserted + after;
        var newCursor = (before + inserted).length;
        textarea.setSelectionRange(newCursor, newCursor);
        hide();
        textarea.focus();
    }

    function currentToken() {
        var cursor = textarea.selectionStart;
        var value = textarea.value;
        var start = cursor;
        while (start > 0 && !/\s/.test(value[start - 1])) start--;
        var token = value.slice(start, cursor);
        if (token.charAt(0) === '@' || token.charAt(0) === '#') {
            return { start: start, trigger: token.charAt(0), partial: token.slice(1) };
        }
        return null;
    }

    function update() {
        var token = currentToken();
        if (!token) { hide(); return; }
        var source = token.trigger === '@' ? names : tags;
        var partialLower = token.partial.toLowerCase();
        currentMatches = (source || []).filter(function (item) {
            return item.toLowerCase().indexOf(partialLower) === 0;
        }).slice(0, 8);
        triggerStart = token.start;
        activeIndex = currentMatches.length ? 0 : -1;
        if (currentMatches.length) {
            position();
            render();
        } else {
            hide();
        }
    }

    textarea.addEventListener('input', update);
    textarea.addEventListener('click', update);
    textarea.addEventListener('blur', function () {
        // Delay so a mousedown selection on the dropdown still lands first.
        setTimeout(hide, 150);
    });
    textarea.addEventListener('keydown', function (e) {
        if (dropdown.style.display === 'none') return;
        if (e.key === 'ArrowDown') {
            e.preventDefault();
            activeIndex = Math.min(activeIndex + 1, currentMatches.length - 1);
            render();
        } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            activeIndex = Math.max(activeIndex - 1, 0);
            render();
        } else if (e.key === 'Enter' || e.key === 'Tab') {
            if (activeIndex >= 0) {
                e.preventDefault();
                select(activeIndex);
            }
        } else if (e.key === 'Escape') {
            hide();
        }
    });
}

// Convenience: attach the widget to every free-text field inside a form
// (by name), given a shared names/tools/tags source. Fields that don't
// exist in the given form (e.g. a page that doesn't have all four) are
// silently skipped. names and tools are combined into one list for "@"
// (deduplicated, in case a tool and a name happen to share a string).
function initMentionsForForm(formSelector, names, tools, tags) {
    var form = document.querySelector(formSelector);
    if (!form) return;
    var mentionables = Array.from(new Set((names || []).concat(tools || [])));
    ['problem_statement', 'action_items', 'current_status', 'follow_up'].forEach(function (fieldName) {
        var el = form.querySelector('textarea[name="' + fieldName + '"]');
        if (el) initMentionAutocomplete(el, mentionables, tags);
    });
}
