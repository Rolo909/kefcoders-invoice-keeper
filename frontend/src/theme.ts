import {
  Button, createTheme, defaultVariantColorsResolver, Drawer, Input, InputWrapper, Menu, Modal, Notification,
  type MantineColorsTuple, type VariantColorsResolver,
} from '@mantine/core';

const stamp: MantineColorsTuple = ['#f0edfb', '#ddd7f4', '#b9aeea', '#9483e0', '#7562d6', '#604cc6', '#4b36b5', '#3f2d9b', '#33247f', '#271b63'];

const resolver: VariantColorsResolver = (input) => {
  const danger = input.color === 'red';
  const tone = danger ? 'var(--red)' : 'var(--violet)';
  const soft = danger ? 'var(--red-soft)' : 'var(--violet-soft)';
  switch (input.variant) {
    case 'filled':
      return { background: tone, hover: danger ? 'var(--red)' : 'var(--violet-2)', color: danger ? 'var(--paper)' : 'var(--on-violet)', border: '1.5px solid transparent' };
    case 'outline':
      return { background: 'transparent', hover: soft, color: tone, border: `1.5px solid ${tone}` };
    case 'subtle':
      return { background: 'transparent', hover: danger ? soft : 'var(--paper-2)', color: danger ? tone : 'var(--ink)', border: '1.5px solid transparent' };
    case 'transparent':
      return { background: 'transparent', hover: 'transparent', color: tone, border: '1.5px solid transparent' };
    default:
      return defaultVariantColorsResolver(input);
  }
};

export const theme = createTheme({
  primaryColor: 'stamp',
  colors: { stamp },
  primaryShade: { light: 6, dark: 3 },
  fontFamily: "'PT Sans', 'Helvetica Neue', Arial, sans-serif",
  fontFamilyMonospace: "'PT Mono', ui-monospace, Menlo, monospace",
  headings: { fontFamily: "'PT Serif', Georgia, serif", fontWeight: '700' },
  defaultRadius: 'xs',
  radius: { xs: '3px', sm: '6px' },
  fontSizes: { sm: '15px', md: '16px' },
  variantColorResolver: resolver,
  components: {
    Button: Button.extend({ defaultProps: { size: 'sm', radius: 'xs' }, classNames: { root: 'ik-btn' } }),
    Input: Input.extend({ classNames: { input: 'ik-input', section: 'ik-section' } }),
    InputWrapper: InputWrapper.extend({ classNames: { label: 'ik-label', description: 'ik-hint', error: 'ik-error' } }),
    Modal: Modal.extend({
      defaultProps: { centered: true, size: 520, overlayProps: { backgroundOpacity: 1 } },
      classNames: { content: 'ik-modal-content', header: 'ik-modal-header', title: 'ik-modal-title', overlay: 'ik-overlay' },
    }),
    Drawer: Drawer.extend({
      defaultProps: { position: 'right', size: 560, overlayProps: { backgroundOpacity: 1 } },
      classNames: { content: 'ik-drawer-content', header: 'ik-drawer-header', overlay: 'ik-overlay' },
    }),
    Menu: Menu.extend({ defaultProps: { shadow: 'md', position: 'bottom-end' }, classNames: { dropdown: 'ik-menu', item: 'ik-menu-item' } }),
    Notification: Notification.extend({
      classNames: { root: 'ik-notification', title: 'ik-notification-title', description: 'ik-notification-description', closeButton: 'ik-notification-close' },
    }),
  },
});
