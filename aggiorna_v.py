import os, shutil

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def backup_and_read(rel_path):
    full_path = os.path.join(BASE_DIR, *rel_path.split("/"))
    if not os.path.exists(full_path):
        raise FileNotFoundError(f"File non trovato: {full_path}")
    shutil.copy2(full_path, full_path + ".bak")
    with open(full_path, "r", encoding="utf-8") as f:
        return full_path, f.read()

def write_file(full_path, content):
    with open(full_path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"[OK] Aggiornato: {full_path}")

# 1. google_api.py
path, code = backup_and_read("google_api.py")
helper_py = '''def parse_score_info(val):
    s = str(val or '').strip().upper()
    has_v = s.startswith('V')
    num_str = s[1:].strip() if has_v else s
    try:
        num = int(float(num_str)) if num_str != '' else 0
    except Exception:
        num = 0
    return num, has_v, s

def safe_get(lst, idx, default=""):'''
assert "def safe_get(lst, idx, default=\"\"):" in code
code = code.replace("def safe_get(lst, idx, default=\"\"):", helper_py, 1)

old_curr_check = '''                    try:
                        p_sx = int(float(m.get('p_sx', '0') or '0'))
                        p_dx = int(float(m.get('p_dx', '0') or '0'))
                    except Exception:
                        p_sx, p_dx = 0, 0
                    
                    if p_sx != 0 or p_dx != 0:
                        current_match_completed = True'''
new_curr_check = '''                    p_sx, v_sx, _ = parse_score_info(m.get('p_sx', '0'))
                    p_dx, v_dx, _ = parse_score_info(m.get('p_dx', '0'))
                    if p_sx != 0 or p_dx != 0 or v_sx or v_dx:
                        current_match_completed = True'''
assert old_curr_check in code
code = code.replace(old_curr_check, new_curr_check, 1)

old_next_check = '''                try:
                    p_sx = int(float(m.get('p_sx', '0') or '0'))
                    p_dx = int(float(m.get('p_dx', '0') or '0'))
                except Exception:
                    p_sx, p_dx = 0, 0
                if p_sx == 0 and p_dx == 0:
                    next_match = m
                    break'''
new_next_check = '''                p_sx, v_sx, _ = parse_score_info(m.get('p_sx', '0'))
                p_dx, v_dx, _ = parse_score_info(m.get('p_dx', '0'))
                if p_sx == 0 and p_dx == 0 and not v_sx and not v_dx:
                    next_match = m
                    break'''
assert old_next_check in code
code = code.replace(old_next_check, new_next_check, 1)

old_verify = '''            try:
                msx = int(float(match_data.get('p_sx', '0') or '0'))
                mdx = int(float(match_data.get('p_dx', '0') or '0'))
                vsx = int(float(payload.get('val_sx', '0') or '0'))
                vdx = int(float(payload.get('val_dx', '0') or '0'))
                
                if msx == vsx and mdx == vdx:'''
new_verify = '''            try:
                msx, mvsx, _ = parse_score_info(match_data.get('p_sx', '0'))
                mdx, mvdx, _ = parse_score_info(match_data.get('p_dx', '0'))
                vsx, vvsx, _ = parse_score_info(payload.get('val_sx', '0'))
                vdx, vvdx, _ = parse_score_info(payload.get('val_dx', '0'))
                
                if msx == vsx and mdx == vdx and mvsx == vvsx and mvdx == vvdx:'''
assert old_verify in code
code = code.replace(old_verify, new_verify, 1)
write_file(path, code)

# 2. app.py
path, code = backup_and_read("app.py")
old_load_scores = '''    try: current_state['fencer_left']['score'] = int(float(d['p_sx']))
    except Exception: current_state['fencer_left']['score'] = 0
    try: current_state['fencer_right']['score'] = int(float(d['p_dx']))
    except Exception: current_state['fencer_right']['score'] = 0'''
new_load_scores = '''    def _num_score(v):
        s = str(v or '').strip().upper()
        if s.startswith('V'): s = s[1:].strip()
        try: return int(float(s)) if s else 0
        except Exception: return 0
    current_state['fencer_left']['score'] = _num_score(d.get('p_sx'))
    current_state['fencer_right']['score'] = _num_score(d.get('p_dx'))'''
assert old_load_scores in code
code = code.replace(old_load_scores, new_load_scores, 1)

old_send_res = '''    val_sx = current_state['fencer_right']['score'] if current_state.get('swapped') else current_state['fencer_left']['score']
    val_dx = current_state['fencer_left']['score'] if current_state.get('swapped') else current_state['fencer_right']['score']'''
new_send_res = '''    val_sx = current_state['fencer_right']['score'] if current_state.get('swapped') else current_state['fencer_left']['score']
    val_dx = current_state['fencer_left']['score'] if current_state.get('swapped') else current_state['fencer_right']['score']
    prio = current_state.get('priority')
    if val_sx == val_dx and prio in ['left', 'right']:
        sx_has_prio = (prio == 'right') if current_state.get('swapped') else (prio == 'left')
        if sx_has_prio: val_sx = f"V{val_sx}"
        else: val_dx = f"V{val_dx}"'''
assert old_send_res in code
code = code.replace(old_send_res, new_send_res, 1)

old_next_app = '''            try: p_sx = int(float(m.get('p_sx', '0') or '0'))
            except Exception: p_sx = 0
            try: p_dx = int(float(m.get('p_dx', '0') or '0'))
            except Exception: p_dx = 0
            if p_sx == 0 and p_dx == 0:'''
new_next_app = '''            s_sx = str(m.get('p_sx', '0') or '0').strip().upper()
            s_dx = str(m.get('p_dx', '0') or '0').strip().upper()
            v_sx = s_sx.startswith('V')
            v_dx = s_dx.startswith('V')
            try: p_sx = int(float(s_sx[1:] if v_sx else s_sx or '0'))
            except Exception: p_sx = 0
            try: p_dx = int(float(s_dx[1:] if v_dx else s_dx or '0'))
            except Exception: p_dx = 0
            if p_sx == 0 and p_dx == 0 and not v_sx and not v_dx:'''
assert old_next_app in code
code = code.replace(old_next_app, new_next_app, 1)

old_bg_res = '''    payload = { 
        "sheet_name": "display3gir", "row": data['row'], 
        "col_sx": letter_to_sheet_col(cols['psx']), "val_sx": data['val_sx'], 
        "col_dx": letter_to_sheet_col(cols['pdx']), "val_dx": data['val_dx'] 
    }'''
new_bg_res = '''    val_sx = str(data.get('val_sx', '')).strip().upper()
    val_dx = str(data.get('val_dx', '')).strip().upper()
    payload = { 
        "sheet_name": "display3gir", "row": data['row'], 
        "col_sx": letter_to_sheet_col(cols['psx']), "val_sx": val_sx, 
        "col_dx": letter_to_sheet_col(cols['pdx']), "val_dx": val_dx 
    }'''
assert old_bg_res in code
code = code.replace(old_bg_res, new_bg_res, 1)
write_file(path, code)

# 3. templates/pannello_unificato.html
path, code = backup_and_read("templates/pannello_unificato.html")
old_rapid_inputs = '''                    <div class="flex items-center gap-1">
                        <input type="number" id="sx_${m.row}" value="${m.p_sx}" class="score-input" 
                               onfocus="onScoreInputFocus(); this.dataset.old = this.value; this.value = '';" 
                               onblur="onScoreInputBlur(); if(this.value === '') this.value = this.dataset.old;"
                               onkeydown="if(event.key==='Enter'){ sendScore('${girone}', ${m.row}, '${m.sx.replace(/'/g, "\\\\'")}', '${m.dx.replace(/'/g, "\\\\'")}'); }">
                        <span class="text-slate-500 font-bold">-</span>
                        <input type="number" id="dx_${m.row}" value="${m.p_dx}" class="score-input"
                               onfocus="onScoreInputFocus(); this.dataset.old = this.value; this.value = '';" 
                               onblur="onScoreInputBlur(); if(this.value === '') this.value = this.dataset.old;"
                               onkeydown="if(event.key==='Enter'){ sendScore('${girone}', ${m.row}, '${m.sx.replace(/'/g, "\\\\'")}', '${m.dx.replace(/'/g, "\\\\'")}'); }">
                    </div>'''
new_rapid_inputs = '''                    <div class="flex items-center gap-1">
                        <input type="text" maxlength="4" id="sx_${m.row}" value="${m.p_sx}" class="score-input uppercase" 
                               oninput="this.value = this.value.toUpperCase();"
                               onfocus="onScoreInputFocus(); this.dataset.old = this.value; this.value = '';" 
                               onblur="onScoreInputBlur(); if(this.value === '') this.value = this.dataset.old;"
                               onkeydown="if(event.key==='Enter'){ sendScore('${girone}', ${m.row}, '${m.sx.replace(/'/g, "\\\\'")}', '${m.dx.replace(/'/g, "\\\\'")}'); }">
                        <span class="text-slate-500 font-bold">-</span>
                        <input type="text" maxlength="4" id="dx_${m.row}" value="${m.p_dx}" class="score-input uppercase"
                               oninput="this.value = this.value.toUpperCase();"
                               onfocus="onScoreInputFocus(); this.dataset.old = this.value; this.value = '';" 
                               onblur="onScoreInputBlur(); if(this.value === '') this.value = this.dataset.old;"
                               onkeydown="if(event.key==='Enter'){ sendScore('${girone}', ${m.row}, '${m.sx.replace(/'/g, "\\\\'")}', '${m.dx.replace(/'/g, "\\\\'")}'); }">
                    </div>'''
assert old_rapid_inputs in code
code = code.replace(old_rapid_inputs, new_rapid_inputs, 1)

old_send_score = '''        function sendScore(girone, row, sxName, dxName) {
            const val_sx = document.getElementById(`sx_${row}`).value;
            const val_dx = document.getElementById(`dx_${row}`).value;
            
            if (val_sx === '' || val_dx === '') {
                showToast("Errore: Inserisci entrambi i punteggi!", "error");
                return;
            }

            forceResumeTabelloneRefresh();
            socket.emit('send_background_result', { girone, row, sx: sxName, dx: dxName, val_sx, val_dx });
        }'''
new_send_score = '''        function parseBoutScore(raw) {
            const str = String(raw ?? '').trim().toUpperCase();
            const hasV = str.startsWith('V');
            const numPart = hasV ? str.slice(1).trim() : str;
            const num = numPart === '' ? 0 : (parseInt(numPart, 10) || 0);
            const isPlayed = (str !== '' && str !== '0') || hasV;
            return { raw: str, num, hasV, isPlayed };
        }

        function isValidBoutInput(val) {
            return /^(V?\\d+|V)$/i.test(String(val ?? '').trim());
        }

        function sendScore(girone, row, sxName, dxName) {
            const elSx = document.getElementById(`sx_${row}`);
            const elDx = document.getElementById(`dx_${row}`);
            const val_sx = elSx.value.trim().toUpperCase();
            const val_dx = elDx.value.trim().toUpperCase();
            elSx.value = val_sx;
            elDx.value = val_dx;
            
            if (val_sx === '' || val_dx === '') {
                showToast("Errore: Inserisci entrambi i punteggi!", "error");
                return;
            }
            if (!isValidBoutInput(val_sx) || !isValidBoutInput(val_dx)) {
                showToast("Formato non valido! Usa numeri o V + numero (es. V4 e 4).", "error");
                return;
            }

            forceResumeTabelloneRefresh();
            socket.emit('send_background_result', { girone, row, sx: sxName, dx: dxName, val_sx, val_dx });
        }'''
assert old_send_score in code
code = code.replace(old_send_score, new_send_score, 1)

old_bouts_logic = '''        // Verifica se un assalto è effettivamente concluso oppure ancora da svolgere / incompleto
        function isBoutCompleted(phase, pSx, pDx, row) {
            if (pSx === 0 && pDx === 0) return false;
            if (pSx === pDx) return false;

            const maxP = Math.max(pSx, pDx);
            if (phase === 'GIRONE') {
                return maxP >= 4;
            } else {
                return maxP >= 10;
            }
        }

        function toggleShowAllBouts(gironeKey) {
            showAllBoutsMap[gironeKey] = !showAllBoutsMap[gironeKey];
            renderTabelloneContent();
        }

        function getGironeBoutsStats(gironeKey) {
            const matches = allGironi[gironeKey] || [];
            const validMatches = matches.filter(m => m.sx && m.dx && m.sx.trim() !== '' && m.dx.trim() !== '');

            if (gironeKey === '32') {
                const all32 = [];
                const pending32 = [];
                validMatches.forEach((m, idx) => {
                    const pSx = parseInt(m.p_sx) || 0;
                    const pDx = parseInt(m.p_dx) || 0;
                    const completed = isBoutCompleted('32', pSx, pDx, m.row);
                    const item = {
                        order: `${idx + 1}°`,
                        phase: '32',
                        row: m.row,
                        sx: m.sx.trim(),
                        dx: m.dx.trim(),
                        p_sx: pSx,
                        p_dx: pDx,
                        isPartial: (!completed && (pSx > 0 || pDx > 0)),
                        isCompleted: completed
                    };
                    all32.push(item);
                    if (!completed) pending32.push(item);
                });
                return {
                    total: validMatches.length,
                    pending: pending32,
                    deTotal: 0,
                    dePending: [],
                    allPendingCombined: pending32,
                    allBoutsCombined: all32,
                    isCompleted: (validMatches.length > 0 && pending32.length === 0)
                };
            }

            const poolAll = validMatches.filter(m => Number(m.row) <= 29);
            const deAll   = validMatches.filter(m => Number(m.row) >= 30);

            const poolFormatted = [];
            const poolPending = [];
            poolAll.forEach((m, idx) => {
                const pSx = parseInt(m.p_sx) || 0;
                const pDx = parseInt(m.p_dx) || 0;
                const completed = isBoutCompleted('GIRONE', pSx, pDx, m.row);
                const item = {
                    order: `${idx + 1}°`,
                    phase: 'GIRONE',
                    row: m.row,
                    sx: m.sx.trim(),
                    dx: m.dx.trim(),
                    p_sx: pSx,
                    p_dx: pDx,
                    isPartial: (!completed && (pSx > 0 || pDx > 0)),
                    isCompleted: completed
                };
                poolFormatted.push(item);
                if (!completed) poolPending.push(item);
            });

            const deFormatted = [];
            const dePending = [];
            deAll.forEach((m) => {
                const pSx = parseInt(m.p_sx) || 0;
                const pDx = parseInt(m.p_dx) || 0;
                const sxClean = m.sx.trim();
                const dxClean = m.dx.trim();
                if (sxClean !== '-' && dxClean !== '-') {
                    const completed = isBoutCompleted('DIRETTA', pSx, pDx, m.row);
                    const item = {
                        order: getDeRoundLabel(Number(m.row)),
                        phase: 'DIRETTA',
                        row: m.row,
                        sx: sxClean,
                        dx: dxClean,
                        p_sx: pSx,
                        p_dx: pDx,
                        isPartial: (!completed && (pSx > 0 || pDx > 0)),
                        isCompleted: completed
                    };
                    deFormatted.push(item);
                    if (!completed) dePending.push(item);
                }
            });'''
new_bouts_logic = '''        // Verifica se un assalto è effettivamente concluso oppure ancora da svolgere / incompleto
        function isBoutCompleted(phase, infoSx, infoDx, row) {
            if (!infoSx.isPlayed && !infoDx.isPlayed) return false;
            if (infoSx.hasV !== infoDx.hasV) return true;
            if (infoSx.num === infoDx.num) return false;

            const maxP = Math.max(infoSx.num, infoDx.num);
            if (phase === 'GIRONE') {
                return maxP >= 4;
            } else {
                return maxP >= 10;
            }
        }

        function toggleShowAllBouts(gironeKey) {
            showAllBoutsMap[gironeKey] = !showAllBoutsMap[gironeKey];
            renderTabelloneContent();
        }

        function getGironeBoutsStats(gironeKey) {
            const matches = allGironi[gironeKey] || [];
            const validMatches = matches.filter(m => m.sx && m.dx && m.sx.trim() !== '' && m.dx.trim() !== '');

            if (gironeKey === '32') {
                const all32 = [];
                const pending32 = [];
                validMatches.forEach((m, idx) => {
                    const infoSx = parseBoutScore(m.p_sx);
                    const infoDx = parseBoutScore(m.p_dx);
                    const completed = isBoutCompleted('32', infoSx, infoDx, m.row);
                    const item = {
                        order: `${idx + 1}°`,
                        phase: '32',
                        row: m.row,
                        sx: m.sx.trim(),
                        dx: m.dx.trim(),
                        p_sx: infoSx.raw || "0",
                        p_dx: infoDx.raw || "0",
                        isPlayed: (infoSx.isPlayed || infoDx.isPlayed),
                        isPartial: (!completed && (infoSx.isPlayed || infoDx.isPlayed)),
                        isCompleted: completed
                    };
                    all32.push(item);
                    if (!completed) pending32.push(item);
                });
                return {
                    total: validMatches.length,
                    pending: pending32,
                    deTotal: 0,
                    dePending: [],
                    allPendingCombined: pending32,
                    allBoutsCombined: all32,
                    isCompleted: (validMatches.length > 0 && pending32.length === 0)
                };
            }

            const poolAll = validMatches.filter(m => Number(m.row) <= 29);
            const deAll   = validMatches.filter(m => Number(m.row) >= 30);

            const poolFormatted = [];
            const poolPending = [];
            poolAll.forEach((m, idx) => {
                const infoSx = parseBoutScore(m.p_sx);
                const infoDx = parseBoutScore(m.p_dx);
                const completed = isBoutCompleted('GIRONE', infoSx, infoDx, m.row);
                const item = {
                    order: `${idx + 1}°`,
                    phase: 'GIRONE',
                    row: m.row,
                    sx: m.sx.trim(),
                    dx: m.dx.trim(),
                    p_sx: infoSx.raw || "0",
                    p_dx: infoDx.raw || "0",
                    isPlayed: (infoSx.isPlayed || infoDx.isPlayed),
                    isPartial: (!completed && (infoSx.isPlayed || infoDx.isPlayed)),
                    isCompleted: completed
                };
                poolFormatted.push(item);
                if (!completed) poolPending.push(item);
            });

            const deFormatted = [];
            const dePending = [];
            deAll.forEach((m) => {
                const infoSx = parseBoutScore(m.p_sx);
                const infoDx = parseBoutScore(m.p_dx);
                const sxClean = m.sx.trim();
                const dxClean = m.dx.trim();
                if (sxClean !== '-' && dxClean !== '-') {
                    const completed = isBoutCompleted('DIRETTA', infoSx, infoDx, m.row);
                    const item = {
                        order: getDeRoundLabel(Number(m.row)),
                        phase: 'DIRETTA',
                        row: m.row,
                        sx: sxClean,
                        dx: dxClean,
                        p_sx: infoSx.raw || "0",
                        p_dx: infoDx.raw || "0",
                        isPlayed: (infoSx.isPlayed || infoDx.isPlayed),
                        isPartial: (!completed && (infoSx.isPlayed || infoDx.isPlayed)),
                        isCompleted: completed
                    };
                    deFormatted.push(item);
                    if (!completed) dePending.push(item);
                }
            });'''
assert old_bouts_logic in code
code = code.replace(old_bouts_logic, new_bouts_logic, 1)

old_quick_send = '''            const val_sx = elSx.value.trim();
            const val_dx = elDx.value.trim();

            if (val_sx === '' || val_dx === '') {
                showToast("Inserisci entrambi i punteggi!", "error");
                return;
            }'''
new_quick_send = '''            const val_sx = elSx.value.trim().toUpperCase();
            const val_dx = elDx.value.trim().toUpperCase();
            elSx.value = val_sx;
            elDx.value = val_dx;

            if (val_sx === '' || val_dx === '') {
                showToast("Inserisci entrambi i punteggi!", "error");
                return;
            }
            if (!isValidBoutInput(val_sx) || !isValidBoutInput(val_dx)) {
                showToast("Formato non valido! Usa numeri o V + numero (es. V4 e 4).", "error");
                return;
            }'''
assert old_quick_send in code
code = code.replace(old_quick_send, new_quick_send, 1)

old_sidebar_inputs = '''                const valSx = draft ? draft.sx : ((b.p_sx > 0 || b.p_dx > 0) ? String(b.p_sx) : "");
                const valDx = draft ? draft.dx : ((b.p_sx > 0 || b.p_dx > 0) ? String(b.p_dx) : "");
                const isDe = (b.phase === 'DIRETTA');
                const badgeClass = isDe
                    ? "bg-[#7a1224] text-white"
                    : "bg-[#f9ebed] text-[#7a1224] border border-[#7a1224]/30";

                const statusTag = b.isPartial
                    ? `<span class="text-[9px] font-bold uppercase px-1.5 py-0.5 rounded bg-amber-100 text-amber-800 border border-amber-300 flex-none">Incompleto</span>`
                    : (b.isCompleted ? `<span class="text-[9px] font-bold uppercase px-1.5 py-0.5 rounded bg-emerald-100 text-emerald-800 flex-none">OK</span>` : '');

                return `
                    <div class="flex items-center justify-between gap-1.5 px-2.5 py-2 ${b.isPartial ? 'bg-amber-50/70' : 'bg-white'} hover:bg-[#f9ebed]/60 transition border-b border-neutral-200 last:border-b-0">
                        <span class="text-[10px] font-mono font-extrabold ${badgeClass} px-1.5 py-0.5 rounded min-w-[38px] text-center flex-none" title="${isDe ? 'Eliminazione Diretta' : 'Assalto Girone'}">${b.order}</span>
                        <div class="flex-1 text-right text-xs font-extrabold text-neutral-800 truncate" title="${b.sx}">${b.sx}</div>
                        <div class="flex items-center gap-1 flex-none">
                            <input type="number" min="0" max="99" id="tb_sx_${gironeKey}_${b.row}" value="${valSx}" placeholder="0"
                                class="wf-mini-input"
                                onfocus="onScoreInputFocus('${gironeKey}', ${b.row})"
                                oninput="onScoreInputChange('${gironeKey}', ${b.row})"
                                onblur="onScoreInputBlur()"
                                onkeydown="if(event.key==='Enter'){ sendQuickBoutFromTabellone('${gironeKey}', ${b.row}, '${safeSx}', '${safeDx}'); }">
                            <span class="text-neutral-400 font-bold text-xs">-</span>
                            <input type="number" min="0" max="99" id="tb_dx_${gironeKey}_${b.row}" value="${valDx}" placeholder="0"
                                class="wf-mini-input"
                                onfocus="onScoreInputFocus('${gironeKey}', ${b.row})"
                                oninput="onScoreInputChange('${gironeKey}', ${b.row})"
                                onblur="onScoreInputBlur()"
                                onkeydown="if(event.key==='Enter'){ sendQuickBoutFromTabellone('${gironeKey}', ${b.row}, '${safeSx}', '${safeDx}'); }">
                        </div>'''
new_sidebar_inputs = '''                const valSx = draft ? draft.sx : (b.isPlayed ? String(b.p_sx) : "");
                const valDx = draft ? draft.dx : (b.isPlayed ? String(b.p_dx) : "");
                const isDe = (b.phase === 'DIRETTA');
                const badgeClass = isDe
                    ? "bg-[#7a1224] text-white"
                    : "bg-[#f9ebed] text-[#7a1224] border border-[#7a1224]/30";

                const statusTag = b.isPartial
                    ? `<span class="text-[9px] font-bold uppercase px-1.5 py-0.5 rounded bg-amber-100 text-amber-800 border border-amber-300 flex-none">Incompleto</span>`
                    : (b.isCompleted ? `<span class="text-[9px] font-bold uppercase px-1.5 py-0.5 rounded bg-emerald-100 text-emerald-800 flex-none">OK</span>` : '');

                return `
                    <div class="flex items-center justify-between gap-1.5 px-2.5 py-2 ${b.isPartial ? 'bg-amber-50/70' : 'bg-white'} hover:bg-[#f9ebed]/60 transition border-b border-neutral-200 last:border-b-0">
                        <span class="text-[10px] font-mono font-extrabold ${badgeClass} px-1.5 py-0.5 rounded min-w-[38px] text-center flex-none" title="${isDe ? 'Eliminazione Diretta' : 'Assalto Girone'}">${b.order}</span>
                        <div class="flex-1 text-right text-xs font-extrabold text-neutral-800 truncate" title="${b.sx}">${b.sx}</div>
                        <div class="flex items-center gap-1 flex-none">
                            <input type="text" maxlength="4" id="tb_sx_${gironeKey}_${b.row}" value="${valSx}" placeholder="0"
                                class="wf-mini-input uppercase"
                                onfocus="onScoreInputFocus('${gironeKey}', ${b.row})"
                                oninput="this.value = this.value.toUpperCase(); onScoreInputChange('${gironeKey}', ${b.row})"
                                onblur="onScoreInputBlur()"
                                onkeydown="if(event.key==='Enter'){ sendQuickBoutFromTabellone('${gironeKey}', ${b.row}, '${safeSx}', '${safeDx}'); }">
                            <span class="text-neutral-400 font-bold text-xs">-</span>
                            <input type="text" maxlength="4" id="tb_dx_${gironeKey}_${b.row}" value="${valDx}" placeholder="0"
                                class="wf-mini-input uppercase"
                                onfocus="onScoreInputFocus('${gironeKey}', ${b.row})"
                                oninput="this.value = this.value.toUpperCase(); onScoreInputChange('${gironeKey}', ${b.row})"
                                onblur="onScoreInputBlur()"
                                onkeydown="if(event.key==='Enter'){ sendQuickBoutFromTabellone('${gironeKey}', ${b.row}, '${safeSx}', '${safeDx}'); }">
                        </div>'''
assert old_sidebar_inputs in code
code = code.replace(old_sidebar_inputs, new_sidebar_inputs, 1)
write_file(path, code)

# 4. templates/inserisci_punti.html
path, code = backup_and_read("templates/inserisci_punti.html")
old_ip = '''                    <div class="flex items-center gap-1">
                        <input type="number" id="sx_${m.row}" value="${m.p_sx}" class="score-input" 
                               onfocus="this.dataset.old = this.value; this.value = '';" 
                               onblur="if(this.value === '') this.value = this.dataset.old;">
                        <span class="text-slate-500 font-bold">-</span>
                        <input type="number" id="dx_${m.row}" value="${m.p_dx}" class="score-input"
                               onfocus="this.dataset.old = this.value; this.value = '';" 
                               onblur="if(this.value === '') this.value = this.dataset.old;">
                    </div>'''
new_ip = '''                    <div class="flex items-center gap-1">
                        <input type="text" maxlength="4" id="sx_${m.row}" value="${m.p_sx}" class="score-input uppercase" 
                               oninput="this.value = this.value.toUpperCase();"
                               onfocus="this.dataset.old = this.value; this.value = '';" 
                               onblur="if(this.value === '') this.value = this.dataset.old;">
                        <span class="text-slate-500 font-bold">-</span>
                        <input type="text" maxlength="4" id="dx_${m.row}" value="${m.p_dx}" class="score-input uppercase"
                               oninput="this.value = this.value.toUpperCase();"
                               onfocus="this.dataset.old = this.value; this.value = '';" 
                               onblur="if(this.value === '') this.value = this.dataset.old;">
                    </div>'''
assert old_ip in code
code = code.replace(old_ip, new_ip, 1)

old_ip_send = '''            const val_sx = document.getElementById(`sx_${row}`).value;
            const val_dx = document.getElementById(`dx_${row}`).value;
            
            if(val_sx === '' || val_dx === '') {
                showToast("Errore: Inserisci entrambi i punteggi!", "error");
                return;
            }'''
new_ip_send = '''            const val_sx = document.getElementById(`sx_${row}`).value.trim().toUpperCase();
            const val_dx = document.getElementById(`dx_${row}`).value.trim().toUpperCase();
            document.getElementById(`sx_${row}`).value = val_sx;
            document.getElementById(`dx_${row}`).value = val_dx;
            
            if(val_sx === '' || val_dx === '') {
                showToast("Errore: Inserisci entrambi i punteggi!", "error");
                return;
            }
            if(!/^(V?\\d+|V)$/i.test(val_sx) || !/^(V?\\d+|V)$/i.test(val_dx)) {
                showToast("Formato non valido! Usa numeri o V + numero (es. V4 e 4).", "error");
                return;
            }'''
assert old_ip_send in code
code = code.replace(old_ip_send, new_ip_send, 1)
write_file(path, code)

# 5. templates/telecomando.html
path, code = backup_and_read("templates/telecomando.html")
old_tel = '''                    const p_sx_val = parseInt(m.p_sx) || 0;
                    const p_dx_val = parseInt(m.p_dx) || 0;
                    
                    if (p_sx_val !== 0 || p_dx_val !== 0) { 
                        opt.style.color = '#ef4444'; 
                        opt.innerText = `🔴 ${m.sx} [${p_sx_val}] - [${p_dx_val}] ${m.dx}`;
                    } else {
                        opt.style.color = '#22c55e'; 
                        opt.innerText = `🟢 ${m.sx} [${p_sx_val}] - [${p_dx_val}] ${m.dx}`;
                    }'''
new_tel = '''                    const rawSx = String(m.p_sx || '0').trim().toUpperCase();
                    const rawDx = String(m.p_dx || '0').trim().toUpperCase();
                    const isPlayed = (rawSx !== '' && rawSx !== '0') || (rawDx !== '' && rawDx !== '0');
                    
                    if (isPlayed) { 
                        opt.style.color = '#ef4444'; 
                        opt.innerText = `🔴 ${m.sx} [${rawSx || '0'}] - [${rawDx || '0'}] ${m.dx}`;
                    } else {
                        opt.style.color = '#22c55e'; 
                        opt.innerText = `🟢 ${m.sx} [0] - [0] ${m.dx}`;
                    }'''
assert old_tel in code
code = code.replace(old_tel, new_tel, 1)
write_file(path, code)

# 6. templates/index.html
path, code = backup_and_read("templates/index.html")
old_idx = "const pending = s.match_list.filter(m => (parseInt(m.p_sx)||0)===0 && (parseInt(m.p_dx)||0)===0);"
new_idx = "const pending = s.match_list.filter(m => { const sx = String(m.p_sx||'0').trim().toUpperCase(); const dx = String(m.p_dx||'0').trim().toUpperCase(); return (sx === '' || sx === '0') && (dx === '' || dx === '0'); });"
assert old_idx in code
code = code.replace(old_idx, new_idx, 1)
write_file(path, code)

print("\n[OK] TUTTI I FILE SONO STATI AGGIORNATI CON SUCCESSO!")
