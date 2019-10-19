thickness = 4; // Wandstärke
width = 160; // x
length = 160; // y
height = 15*2+27;
$fn = 72;

difference()
{
    union()
    {
        // Grundplatte
        cube([width, length, thickness]);

        // Wand links (Kaltgerätestecker)
        translate([-thickness, 0, 0])
        cube([thickness, length, height]);

        // Wand rechts (Antenne)
        translate([width, 0, 0])
        cube([thickness, length, height]);

        // Wand oben
        translate([-thickness, length, 0])
        cube([width+2*thickness, thickness, height]);

        // Wand unten
        translate([-thickness, -thickness, 0])
        cube([width+2*thickness, thickness, height]);

        // Stütze für Kaltgerätestecker
        translate([0, 0, thickness])
        cube([6, 48+8, 15]);
        
        // Stütze für 433
        translate([width-10-16, length-10-62, thickness])
        cube([16, 32, 6]);
        
        // TODO remove dummy pi board
        translate([10, length-10-56, thickness+10])
        #cube([85, 56, 20]);
        
        // Stützen für Pi
        translate([15+3.5, length-10-3.5, thickness])
        #cylinder(d=7, h=10);
        
        translate([15+3.5+58, length-10-3.5, thickness])
        #cylinder(d=7, h=10);
        
        translate([15+3.5, length-10-3.5-49, thickness])
        #cylinder(d=7, h=10);
        
        translate([15+3.5+58, length-10-3.5-49, thickness])
        #cylinder(d=7, h=10);
    }

    // Aussparung für Kaltgerätestecker
    translate([-thickness-1, 8, thickness+15])
    cube([thickness+2, 48, 27]);
    // TODO dummy: 
    translate([-thickness-1, 8, thickness+15])
    cube([thickness+2, 48, height]);

    // Löcher für Netzteil
    translate([width-15-10, 25+10, -1])
    cylinder(d=3, h=thickness+2);

    translate([width-15-10-38.5, 25+10, -1])
    cylinder(d=3, h=thickness+2);
}