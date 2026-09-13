/**
 * System registration entry point. Importing this module registers the three
 * curated Beathi visual systems exactly once (plan §4.3).
 */
import './editorial-typography.js';
import './graphic-field.js';
import './media-slice.js';

export * from './registry.js';
