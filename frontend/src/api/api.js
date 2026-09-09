/* Back-compat shim. The app now uses ./client and ./index (resource modules). */
import client from './client';
export { apiError } from './client';
export default client;
