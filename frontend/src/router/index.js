import { createRouter, createWebHistory } from 'vue-router';
import SettingsView from '../views/SettingsView.vue';
import DashboardView from '../views/DashboardView.vue';

export default createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'dashboard', component: DashboardView },
    { path: '/settings', name: 'settings', component: SettingsView },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
});
