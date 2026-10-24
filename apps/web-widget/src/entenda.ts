// Campaign page "Entenda antes de mexer" (entenda/index.html). The page is
// static HTML; this module only brings in the site's styles and keeps the
// campaign origin for this tab, so "Começar meu perfil" (a plain link to /)
// carries it into the sign-up. No other behaviour, no third-party code.
import { captureAttribution } from './attribution';
import './styles.css';
import './entenda.css';

captureAttribution();
