---
title: "Glimerz Admin Workspace"
layout: "blank"
url: "/admin.html"
outputs: ["html"]
---
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Glimerz Admin Workspace</title>
  
  <!-- Standalone Decap CMS Application Styles and Scripts -->
  <link rel="stylesheet" href="https://unpkg.com@^3.0.0/dist/decap-cms.css" />
  
  <script type="text/javascript">
    window.CMS_MANUAL_INIT = true;
  </script>
  <script src="https://unpkg.com@^3.0.0/dist/decap-cms.js"></script>
</head>
<body>
  <script type="text/javascript">
    CMS.init({
      config: {
        backend: {
          name: 'git-gateway',
          repo: 'kmbajwa1972/Glimerz-site',
          branch: 'main',
          auth_type: 'pkce',
          base_url: 'https://decapbridge.com',
          auth_endpoint: '/sites/087b36a3-18d5-48e4-ae18-5bcb264a8d9f/pkce',
          auth_token_endpoint: '/sites/087b36a3-18d5-48e4-ae18-5bcb264a8d9f/token',
          gateway_url: 'https://decapbridge.com'
        },
        logo_url: 'https://glimerz.com',
        site_url: 'https://glimerz.com',
        media_folder: 'images',
        public_folder: '/images',
        collections: [{
          name: 'blog',
          label: 'Blog Posts',
          folder: '_posts',
          create: true,
          slug: '{{year}}-{{month}}-{{day}}-{{slug}}',
          fields: [
            {label: 'Post Title', name: 'title', widget: 'string'},
            {label: 'Publish Date', name: 'date', widget: 'datetime'},
            {label: 'Featured Image (Upload from PC)', name: 'image', widget: 'image'},
            {label: 'Blog Content & Affiliate Links', name: 'body', widget: 'markdown'}
          ]
        }]
      }
    });
  </script>
</body>
</html>
