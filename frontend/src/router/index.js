import { createRouter, createWebHistory } from 'vue-router';
import SettingsView from '../views/SettingsView.vue';
import DashboardView from '../views/DashboardView.vue';
import GeneratorView from '../views/GeneratorView.vue';

export default createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'dashboard', component: DashboardView },
    { path: '/settings', name: 'settings', component: SettingsView },
    { path: '/generator', name: 'generator', component: GeneratorView },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
});
