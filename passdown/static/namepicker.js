// Reusable multi-value picker: lets the person pick more than one name
// (e.g. from a datalist) and builds a comma-separated value into a
// hidden <input> for normal form submission. Each pick shows as a
// removable chip.
//
// Clicking "Add" (or pressing Enter) stages whatever's typed, even free
// text not in the datalist — that's an explicit action. If the form is
// submitted with unstaged text still sitting in the box, it's committed
// automatically too, but only when it matches a known name from the
// datalist (case-insensitive); otherwise it's left as-is and the form
// submits without it.
//
// initialNamesCsv (optional): a comma-separated string of names to
// pre-populate as chips, e.g. an entry's existing author list on the
// edit page.
function initNamePicker(containerId, initialNamesCsv) {
    var container = document.getElementById(containerId);
    if (!container) return;

    var textInput = container.querySelector('.namepicker-text');
    var addButton = container.querySelector('.namepicker-add');
    var hiddenInput = container.querySelector('.namepicker-hidden');
    var chipList = container.querySelector('.namepicker-chips');
    var names = [];

    if (initialNamesCsv) {
        initialNamesCsv.split(',').forEach(function (n) {
            var trimmed = n.trim();
            if (trimmed && names.indexOf(trimmed) === -1) names.push(trimmed);
        });
    }

    // Case-insensitive match against the datalist, returning the
    // datalist's own casing (so "alan" matches and stores as "Alan").
    function matchKnownName(value) {
        var lower = value.trim().toLowerCase();
        if (!lower) return null;
        var listId = textInput.getAttribute('list');
        var datalist = listId ? document.getElementById(listId) : null;
        if (!datalist) return null;
        var options = datalist.querySelectorAll('option');
        for (var i = 0; i < options.length; i++) {
            if (options[i].value.toLowerCase() === lower) return options[i].value;
        }
        return null;
    }

    function sync() {
        hiddenInput.value = names.join(', ');
        chipList.innerHTML = '';
        names.forEach(function (name, idx) {
            var chip = document.createElement('span');
            chip.className = 'namepicker-chip';

            var label = document.createElement('span');
            label.textContent = name;

            var remove = document.createElement('button');
            remove.type = 'button';
            remove.className = 'namepicker-chip-remove';
            remove.setAttribute('aria-label', 'Remove ' + name);
            remove.textContent = '\u00d7';
            remove.addEventListener('click', function () {
                names.splice(idx, 1);
                sync();
            });

            chip.appendChild(label);
            chip.appendChild(remove);
            chipList.appendChild(chip);
        });
    }

    function stage(value) {
        value = (value || '').trim();
        if (!value) return false;
        if (names.indexOf(value) === -1) {
            names.push(value);
            return true;
        }
        return false;
    }

    // Explicit Add / Enter: free text is fine, this is a deliberate action.
    function addCurrentValue() {
        if (stage(textInput.value)) sync();
        textInput.value = '';
        textInput.focus();
    }

    addButton.addEventListener('click', addCurrentValue);
    textInput.addEventListener('keydown', function (e) {
        if (e.key === 'Enter') {
            e.preventDefault();
            addCurrentValue();
        }
    });

    // Commit unstaged text on submit, but only if it matches a known name.
    var form = container.closest('form');
    if (form) {
        form.addEventListener('submit', function () {
            var pending = textInput.value.trim();
            if (!pending) return;
            var matched = matchKnownName(pending);
            if (matched && stage(matched)) {
                textInput.value = '';
                sync();
            }
        });
    }

    sync();
}
