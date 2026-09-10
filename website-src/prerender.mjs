import {createServer} from 'vite';
import {readFile,writeFile} from 'node:fs/promises';
import {resolve} from 'node:path';
const server=await createServer({server:{middlewareMode:true},appType:'custom'});
try{
 const {App}=await server.ssrLoadModule('/src/App.jsx');
 const React=await import('react');
 const {renderToString}=await import('react-dom/server');
 const html=renderToString(React.createElement(App));
 const target=resolve('../website/index.html');
 const shell=await readFile(target,'utf8');
 if(!shell.includes('<div id="root"></div>'))throw Error('Expected empty build root');
 await writeFile(target,shell.replace('<div id="root"></div>',`<div id="root">${html}</div>`));
 console.log(`Prerendered VELO homepage: ${html.length} characters`);
}finally{await server.close()}
