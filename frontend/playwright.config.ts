import {defineConfig} from '@playwright/test';
export default defineConfig({testDir:'./tests',timeout:120000,workers:1,retries:0,use:{baseURL:'http://127.0.0.1:8000',viewport:{width:1440,height:1100},trace:'retain-on-failure'},outputDir:'../data/browser-results',reporter:[['list'],['json',{outputFile:'../data/browser-results/report.json'}]]});
