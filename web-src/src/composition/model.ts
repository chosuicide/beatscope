import schema from '../../../beatscope/data/composition-schema.json';
import { canonicalJson } from '../direction/contract';

export interface CompositionObject {
  id: string; kind: 'text' | 'image' | 'video'; name: string;
  visible: boolean; locked: boolean; opacity: number;
  transform: { x: number; y: number; width: number; height: number; rotation: number };
  crop: { left: number; right: number; top: number; bottom: number };
  text: string; font_size: number; color: string; asset_id: string;
  source_offset: number; loop: boolean;
}
export interface CompositionResponse {
  id: string; target_id: string; driver: 'ranked_onsets' | 'beats';
  band: 'all' | 'low' | 'mid' | 'high'; motion: 'scale_pulse' | 'opacity_dip';
  amount: number; release: number; min_gap: number;
}
export interface Composition {
  schema: 'beatscope-composition-1'; project_id: string; source_rhythm_sha256: string;
  title: string; artwork: { width: number; height: number; color: string };
  background: { preset_id: string; mode: 'solid' | 'original-renderer'; opacity: number };
  objects: CompositionObject[]; responses: CompositionResponse[]; author_notes: string;
}
type Rule = {type?: string; enum?: string[]; properties?: Record<string, Rule>; required?: string[];
  items?: Rule; maxItems?: number; minimum?: number; maximum?: number; maxLength?: number; pattern?: string};

export function validateComposition(document: unknown, assets?: Set<string>): string[] {
  const errors: string[] = [];
  function walk(v: unknown, r: Rule, path: string) {
    if (r.enum) { if (typeof v !== 'string' || !r.enum.includes(v)) errors.push(path + ':enum'); return; }
    const kind = Array.isArray(v) ? 'array' : v === null ? 'null' : typeof v;
    if (kind !== r.type) { errors.push(path + ':type'); return; }
    if (kind === 'object') {
      const value = v as Record<string, unknown>;
      for (const key of r.required!) if (!Object.hasOwn(value, key)) errors.push(path + '.' + key + ':required');
      for (const [key, child] of Object.entries(value)) {
        if (!Object.hasOwn(r.properties!, key)) errors.push(path + '.' + key + ':unknown');
        else walk(child, r.properties![key], path + '.' + key);
      }
    } else if (kind === 'array') {
      if ((v as unknown[]).length > r.maxItems!) { errors.push(path + ':length'); return; }
      (v as unknown[]).forEach((child, i) => walk(child, r.items!, path + '[' + i + ']'));
    } else if (kind === 'number') {
      if (!Number.isFinite(v) || (v as number) < r.minimum! || (v as number) > r.maximum!) errors.push(path + ':range');
    } else if (kind === 'string') {
      const text = v as string;
      if (text.length > r.maxLength!) errors.push(path + ':length');
      if (r.pattern && !new RegExp(r.pattern + '(?![\\s\\S])').test(text)) errors.push(path + ':pattern');
      for (const char of text) { const code = char.codePointAt(0)!; if (code >= 0xd800 && code <= 0xdfff) { errors.push(path + ':unicode'); break; } }
    }
  }
  walk(document, schema as Rule, '$');
  if (errors.length) return errors;
  const doc = document as Composition, ids = new Set<string>(), responses = new Set<string>();
  for (const o of doc.objects) {
    if (ids.has(o.id)) errors.push('objects:duplicate-id'); ids.add(o.id);
    if (o.crop.left + o.crop.right >= 1 || o.crop.top + o.crop.bottom >= 1) errors.push('objects:crop-empty');
    if (o.kind !== 'text' && (!o.asset_id || (assets && !assets.has(o.asset_id)))) errors.push('objects:asset-missing');
  }
  for (const r of doc.responses) {
    if (responses.has(r.id)) errors.push('responses:duplicate-id'); responses.add(r.id);
    if (!ids.has(r.target_id)) errors.push('responses:target-missing');
  }
  if ((doc.background.mode === 'solid') !== (doc.background.preset_id === '')) errors.push('background:mode-mismatch');
  return errors;
}

export function serializeComposition(doc: Composition): string {
  let errors = validateComposition(doc);
  if (errors.length) throw Error(errors.join('; '));
  const chunks: string[] = []; canonicalJson(doc, chunks);
  const value = chunks.join('');
  if (new TextEncoder().encode(value).byteLength > 1024 * 1024) throw Error('Composition exceeds the 1 MiB document limit.');
  errors = validateComposition(JSON.parse(value));
  if (errors.length) throw Error(errors.join('; '));
  return value;
}

export class CompositionHistory {
  private past: Composition[] = [];
  private future: Composition[] = [];
  constructor(public current: Composition) { this.current = JSON.parse(serializeComposition(current)); }
  get canUndo() { return this.past.length > 0; }
  get canRedo() { return this.future.length > 0; }
  edit(change: (draft: Composition) => void) {
    const next: Composition = structuredClone(this.current); change(next);
    const bytes = serializeComposition(next);
    if (bytes === serializeComposition(this.current)) return false;
    this.past.push(this.current); if (this.past.length > 100) this.past.shift();
    this.current = JSON.parse(bytes); this.future = []; return true;
  }
  undo() { const prev = this.past.pop(); if (prev) { this.future.push(this.current); this.current = prev; } }
  redo() { const next = this.future.pop(); if (next) { this.past.push(this.current); this.current = next; } }
}
