"use strict"
// any 3rd-party modules here
let fs = require('fs');
// load the app to call into
let app = require('./app');
let util = require('util');
console.log('app - \n\t', util.inspect(app, false, null));

// simple error handling
function gen_error(code, msg) {
    return { error: code, msg: msg }
}

function run(req) {
    let ms = req['method'].split('.');
    let iface_name = ms[0];
    let func_name = ms[1];
    let params = req['params'];

    // get the iface, then the func, and call it dync
    if (iface_name in app) {
        let iface_impl = app[iface_name];
        
        if (func_name in iface_impl) {
            let func_impl = iface_impl[func_name];
            let resp = func_impl.apply(iface_impl, params);
            // return the result
            return { result: resp }
        }
        else { return gen_error(-32601, 'Method not found') }
    }
    else { return gen_error(-32601, 'Service not found') }
}

// top-level error handling
process.on('uncaughtException', function(err) {
    console.log('Uncaught Exception - %s', err)
    let resp = gen_error(-32000, err.toString())
    fs.writeFileSync('./service_resp.json', JSON.stringify(resp), 'utf8');
    process.exit(0);
})

// Main
// open the json req
let req = JSON.parse(fs.readFileSync('./service_req.json', 'utf8'));
// run the command
let resp = run(req)
console.log('res - %j', resp);
// save the json resp
fs.writeFileSync('./service_resp.json', JSON.stringify(resp), 'utf8');
process.exit(0);

