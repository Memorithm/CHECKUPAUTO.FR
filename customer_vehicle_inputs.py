"""Shared vehicle grammar and accessible input assistance; never guess an identifier."""
from __future__ import annotations

import datetime as dt
import json
import re

SIV_PATTERN = r"[A-HJ-NP-TV-Z]{2}[0-9]{3}[A-HJ-NP-TV-Z]{2}"
FNI_PATTERN = r"([0-9]{1,4})([A-Z]{1,3})([0-9]{2,3}|2[AB])"
FORMULA_PATTERN = r"[0-9]{4}[A-Z]{2}[0-9]{5}"
SEPARATORS = r"[\s\u2010-\u2015\u2212-]+"
FORMULA_FIRST_YEAR = 2009


def compact_identifier(value: object) -> str:
    # ASCII-only uppercasing avoids converting an invalid Unicode letter to SS.
    raw = str(value or "").translate(str.maketrans(
        "abcdefghijklmnopqrstuvwxyz", "ABCDEFGHIJKLMNOPQRSTUVWXYZ"))
    return re.sub(SEPARATORS, "", raw)


VEHICLE_INPUT_CSS = """
.vehicle-input-feedback{font-size:12px;font-weight:400;line-height:1.45;color:var(--muted);overflow-wrap:anywhere}
.vehicle-input-feedback.invalid{color:#8c3a31}
input[aria-invalid="true"]{border-color:#8c3a31}
"""


def vehicle_inputs_script(today: dt.date | None = None) -> str:
    today = today or dt.date.today()
    rules = {"siv": SIV_PATTERN, "fni": FNI_PATTERN, "formula": FORMULA_PATTERN,
             "firstYear": FORMULA_FIRST_YEAR, "year": today.year,
             "today": today.isoformat()}
    return _SCRIPT.replace("__VEHICLE_RULES__", json.dumps(rules))


_SCRIPT = r"""
const CheckupAutoVehicleInputs = (() => {
  'use strict';
  const rules = __VEHICLE_RULES__;
  const patterns = Object.fromEntries(['siv','fni','formula'].map(
    key => [key, new RegExp('^(?:'+rules[key]+')$')]));
  const upper = value => String(value || '').replace(/[a-z]/g, c => c.toUpperCase());
  const compact = value => upper(value).replace(/[\s\u2010-\u2015\u2212-]+/g, '');
  const separator = c => /[\s\u2010-\u2015\u2212-]/.test(c);
  const hint = system => system === 'fni'
    ? 'FNI : 1 à 4 chiffres, 1 à 3 lettres, puis le département (ex. 1234 AB 78, 123 AB 2A ou 123 AB 971). Espaces automatiques.'
    : 'SIV : 2 lettres, 3 chiffres et 2 lettres (ex. AA-123-AA). Tirets automatiques.';
  const formulaHint = 'Année sur 4 chiffres, puis 2 lettres et 5 chiffres : 2020AB12345.';
  const registrationError = (value, system) => {
    const raw = compact(value);
    if (!patterns[system]?.test(raw)) return hint(system);
    if (system === 'siv') {
      if (raw.slice(0,2) === 'SS' || raw.slice(5) === 'SS' || raw.slice(2,5) === '000')
        return 'Vérifiez les groupes de votre immatriculation SIV sur la carte grise.';
    } else {
      const parts = raw.match(patterns.fni);
      if (Number(parts[1]) === 0 || /^0+$/.test(parts[3]))
        return 'Vérifiez le numéro et le département de votre immatriculation FNI.';
    }
    return '';
  };
  const formulaError = value => {
    const raw = compact(value);
    if (!patterns.formula.test(raw)) return formulaHint;
    const year = Number(raw.slice(0,4));
    return year < rules.firstYear || year > rules.year
      ? 'L’année au début du numéro de formule doit être comprise entre '+rules.firstYear+' et '+rules.year+'.'
      : '';
  };
  const formatRegistration = (value, system, eager = true) => {
    const raw = compact(value);
    if (system === 'fni') {
      const parts = raw.match(/^([0-9]+)([A-Z]*)(.*)$/);
      if (!parts) return raw;
      const [,number,letters,department] = parts;
      if (!letters) return number + department + (eager && number.length === 4 && !department ? ' ' : '');
      return number+' '+letters+(department ? ' '+department : eager && letters.length === 3 ? ' ' : '');
    }
    // Invalid or excess characters stay visible and invalid; never truncate.
    if (!/^(?:[A-Z]{0,2}|[A-Z]{2}[0-9]{0,3}|[A-Z]{2}[0-9]{3}[A-Z]{0,2})$/.test(raw)) return raw;
    let result = raw.slice(0,2);
    if (raw.length > 2 || eager && raw.length === 2) result += '-'+raw.slice(2,5);
    if (raw.length > 5 || eager && raw.length === 5) result += '-'+raw.slice(5);
    return result;
  };
  const caretAt = (value, count) => {
    if (!count) return 0;
    let seen=0, index=0;
    while (index < value.length && seen < count) {
      if (!separator(value[index])) seen++;
      index++;
    }
    while (index < value.length && separator(value[index])) index++;
    return index;
  };
  const rewrite = (input, formatter) => {
    const before=input.value, start=input.selectionStart, end=input.selectionEnd;
    const value=formatter(before);
    if (value === before) return;
    input.value=value;
    if (start !== null && end !== null) input.setSelectionRange(
      caretAt(value,compact(before.slice(0,start)).length),
      caretAt(value,compact(before.slice(0,end)).length));
  };
  const bind = ({system, registration, formula, issueDate, registrationFeedback, formulaFeedback}) => {
    const touched = new WeakSet();
    [registration,formula].forEach(input => {
      // maxlength can silently discard the tail of a formatted paste.
      input.removeAttribute('maxlength');
      input.autocapitalize='characters'; input.spellcheck=false;
      input.setAttribute('autocorrect','off'); input.inputMode='text';
    });
    issueDate.min='1900-01-01'; issueDate.max=rules.today;
    const update = (input, feedback, error, help, force=false) => {
      const message = input.disabled || !input.required && !input.value ? '' : error;
      input.setCustomValidity(message);
      const show = !input.disabled && !!message && (!!input.value || force || touched.has(input));
      input.setAttribute('aria-invalid',String(show));
      feedback.classList.toggle('invalid',show);
      feedback.textContent = show ? message : input.value && !message && !input.disabled
        ? 'Format cohérent. Vérifiez la correspondance avec votre carte grise.' : help;
    };
    const refresh = (force=false) => {
      update(registration,registrationFeedback,registrationError(registration.value,system.value),hint(system.value),force);
      update(formula,formulaFeedback,formulaError(formula.value),formulaHint,force);
    };
    registration.addEventListener('input', event => {
      if (event.isComposing) return;
      const raw=compact(registration.value);
      const detected=/^[0-9]/.test(raw) ? 'fni' : /^[A-Z]/.test(raw) ? 'siv' : '';
      if (detected && system.value !== detected) {
        system.value=detected; system.dispatchEvent(new Event('change',{bubbles:true}));
      }
      rewrite(registration,value=>formatRegistration(value,system.value,!String(event.inputType||'').startsWith('delete')));
      refresh();
    });
    // Deletion next to an inserted separator must not get stuck.
    registration.addEventListener('beforeinput', event => {
      const start=registration.selectionStart, end=registration.selectionEnd;
      if (event.isComposing || !event.cancelable || start !== end || start === null) return;
      let left=start, right=end;
      if (event.inputType === 'deleteContentBackward' && left > 0 && separator(registration.value[left-1])) {
        while (left > 0 && separator(registration.value[left-1])) left--;
        if (left > 0) left--;
      } else if (event.inputType === 'deleteContentForward' && right < registration.value.length && separator(registration.value[right])) {
        while (right < registration.value.length && separator(registration.value[right])) right++;
        if (right < registration.value.length) right++;
      } else return;
      event.preventDefault(); registration.setRangeText('',left,right,'start');
      registration.dispatchEvent(new InputEvent('input',{bubbles:true,inputType:event.inputType}));
    });
    formula.addEventListener('input', event => {
      if (event.isComposing) return;
      rewrite(formula,compact); refresh();
    });
    [registration,formula].forEach(input => {
      input.addEventListener('compositionend',()=>input.dispatchEvent(new Event('input',{bubbles:true})));
      input.addEventListener('change',()=>input.dispatchEvent(new Event('input',{bubbles:true})));
      input.addEventListener('blur',()=>{
        touched.add(input);
        if (input === registration) rewrite(input,value=>formatRegistration(value,system.value,false));
        refresh();
      });
      input.addEventListener('invalid',()=>{touched.add(input);refresh();});
    });
    refresh();
    return {refresh, validate:()=>{refresh(true);return registration.form.reportValidity();}};
  };
  return {compact,formatRegistration,registrationError,formulaError,bind};
})();
"""
