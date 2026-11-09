import { addIcon } from '@iconify/vue/offline';
import icons from 'virtual:dnfgm-offline-icons';

/** The management UI must work with connect-src 'self' and without public icon APIs. */
export function setupIconifyOffline() {
  for (const [name, data] of Object.entries(icons)) addIcon(name, data);
}
