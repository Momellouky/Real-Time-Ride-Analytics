import { createRouter, createWebHistory } from 'vue-router';
import SettingsView from '../views/SettingsView.vue';
import DashboardView from '../views/DashboardView.vue';
import GeneratorView from '../views/GeneratorView.vue';
import DashboardV2View from '../views/DashboardV2View.vue';

export default createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/dashboard-v2', name: 'dashboard-v2', component: DashboardV2View },
    { path: '/', name: 'dashboard', component: DashboardView },
    { path: '/settings', name: 'settings', component: SettingsView },
    { path: '/generator', name: 'generator', component: GeneratorView },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
});
