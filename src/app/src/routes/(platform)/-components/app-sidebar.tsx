import { Link, useLocation, useNavigate } from "@tanstack/react-router";
import { ChevronUpIcon, LayoutDashboardIcon, LogOutIcon, ScrollTextIcon, UserCircle2Icon } from "lucide-react";
import { useAuth } from "#/components/auth-provider";
import { Avatar, AvatarFallback } from "#/components/ui/avatar";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "#/components/ui/dropdown-menu";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  useSidebar,
} from "#/components/ui/sidebar";

const navigation = [
  { label: "Dashboard", href: "/dashboard", icon: LayoutDashboardIcon },
  { label: "Logs", href: "/logs", icon: ScrollTextIcon },
];

export function AppSidebar() {
  const { state } = useSidebar();
  const location = useLocation();
  const navigate = useNavigate();
  const { user, signOut } = useAuth();

  const avatarInitials = (user?.email ?? "?").slice(0, 2).toUpperCase();

  const onSignOut = async () => {
    await signOut();
    await navigate({ to: "/auth" });
  };

  return (
    <Sidebar collapsible={"icon"}>
      <SidebarHeader className={"h-12 shrink-0 items-center justify-center border-b px-4"}>
        {state === "collapsed" ? (
          <>
            <img alt="Logdog" className="h-6 w-auto dark:hidden" src="/icon.png" />
            <img alt="Logdog" className="hidden h-6 w-auto dark:block" src="/icon-dark.png" />
          </>
        ) : (
          <>
            <img alt="Logdog" className="h-8 w-auto dark:hidden" src="/logo.png" />
            <img alt="Logdog" className="hidden h-8 w-auto dark:block" src="/logo-dark.png" />
          </>
        )}
      </SidebarHeader>

      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupContent>
            <SidebarMenu>
              {navigation.map((item) => (
                <SidebarMenuItem key={item.href}>
                  <SidebarMenuButton asChild isActive={location.pathname === item.href} tooltip={item.label}>
                    <Link to={item.href}>
                      <item.icon />
                      <span>{item.label}</span>
                    </Link>
                  </SidebarMenuButton>
                </SidebarMenuItem>
              ))}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>

      <SidebarFooter>
        <SidebarMenu>
          <SidebarMenuItem>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <SidebarMenuButton size={"lg"} tooltip={user?.email}>
                  <Avatar size={"sm"}>
                    <AvatarFallback>{avatarInitials}</AvatarFallback>
                  </Avatar>
                  <span className={"flex-1 truncate text-sm"}>{user?.email}</span>
                  <ChevronUpIcon className={"ml-auto"} />
                </SidebarMenuButton>
              </DropdownMenuTrigger>

              <DropdownMenuContent align={"start"} side={"top"}>
                <DropdownMenuLabel className={"truncate"}>{user?.email}</DropdownMenuLabel>
                <DropdownMenuSeparator />
                <DropdownMenuItem>
                  <UserCircle2Icon />
                  Signed in
                </DropdownMenuItem>
                <DropdownMenuItem onClick={() => void onSignOut()} variant={"destructive"}>
                  <LogOutIcon />
                  Sign out
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarFooter>
    </Sidebar>
  );
}
