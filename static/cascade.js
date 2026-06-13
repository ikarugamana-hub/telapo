function setupCascadingSelect(prefectureSelectId, municipalitySelectId, selectedMunicipality, placeholderLabel) {
    fetch('/static/areas.json')
        .then(res => res.json())
        .then(areas => {
            const prefSelect = document.getElementById(prefectureSelectId);
            const muniSelect = document.getElementById(municipalitySelectId);

            function populate(keepSelection) {
                const pref = prefSelect.value;
                const toSelect = keepSelection ? selectedMunicipality : null;
                muniSelect.innerHTML = '';

                const placeholderOpt = document.createElement('option');
                placeholderOpt.value = '';
                placeholderOpt.textContent = placeholderLabel;
                muniSelect.appendChild(placeholderOpt);

                if (pref && areas[pref]) {
                    areas[pref].forEach(city => {
                        const opt = document.createElement('option');
                        opt.value = city;
                        opt.textContent = city;
                        if (city === toSelect) {
                            opt.selected = true;
                        }
                        muniSelect.appendChild(opt);
                    });
                }
            }

            prefSelect.addEventListener('change', () => populate(false));
            populate(true);
        });
}
